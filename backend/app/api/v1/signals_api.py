import copy
import threading
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi import APIRouter, Body, HTTPException, Query
from app.backtesting.point_in_time_intelligence import build_candle_intelligence_as_of
from app.backtesting.replay_contract import build_point_in_time_stack
from app.contracts.signals import SignalBatchResponse, SignalResponse
from app.contracts.specialized import (
    FrozenDecisionEvaluationRequest,
    FrozenDecisionEvaluationResponse,
    SymbolContextResponse,
)
from app.services.decision_evaluation_service import evaluate_frozen_decision

from app.database.models.market_candles import MarketCandle
from app.database.sqlserver import SessionLocal
from app.intelligence.contradiction_engine import build_contradiction_report
from app.intelligence.data_quality_ledger import build_data_quality_observability
from app.intelligence.probability_engine import build_probability_profile
from app.intelligence.master_ai_engine import generate_master_signal
from app.intelligence.master_ai_engine import score_master_signal_components
from app.intelligence.multi_timeframe_engine import combine_timeframe_signals
from app.intelligence.scenario_engine import build_scenario_plan
from app.intelligence.trade_setup_engine import build_entry_trigger_decision
from app.intelligence.trade_setup_engine import build_trade_setup_decision
from app.repositories.ai_signal_repository import AISignalRepository
from app.repositories.candle_repository import get_candles_as_of
from app.repositories.candle_repository import get_latest_candle
from app.repositories.data_quality_event_repository import DataQualityEventRepository
from app.repositories.intelligence_repository import get_ai_inputs
from app.repositories.master_signal_repository import MasterSignalRepository
from app.repositories.market_participation_repository import MarketParticipationRepository
from app.repositories.paper_trade_repository import PaperTradeRepository
from app.repositories._db_utils import safe_rollback
from app.repositories.risk_repository import RiskRepository
from app.repositories.symbol_repository import SymbolRepository
from app.repositories.trade_plan_repository import TradePlanRepository
from app.risk.risk_engine import RiskEngine
from app.features.point_in_time_feature_service import build_decision_snapshot
from app.features.point_in_time_feature_service import persist_decision_snapshot
from app.trading.trade_plan_engine import build_trade_plan
from app.trading.futures_cost_model import DEFAULT_FEE_BPS
from app.trading.market_participation_guard import evaluate_market_participation
from app.paper_trading.exit_policy import approval_target_for_policy
from app.observability.performance_budget import LatencyBudget
from app.observability.performance_budget import build_stage_latency_report
from app.utils.freshness import candle_freshness_timestamp, freshness_status
from app.utils.freshness import stale_after_seconds_for_timeframe
from app.utils.signal_validation import validate_trade_plan_direction


router = APIRouter(prefix="/signals", tags=["Signals"])
_risk_engine = RiskEngine()
SUPPORTED_TIMEFRAMES = {"1m", "5m", "15m", "1h", "2h", "4h", "1d"}
DEFAULT_TIMEFRAME_STACK = ["1h", "2h", "4h", "1d"]
TIMEFRAME_MODES = {
    "scalp": ["1h", "2h", "4h", "1d"],
    "intraday": ["1h", "2h", "4h", "1d"],
    "swing": ["1h", "2h", "4h", "1d"],
    "position": ["1h", "2h", "4h", "1d"],
}
PREDICTION_TIMEFRAME_STACK = ["1h", "2h", "4h", "1d"]
ENTRY_TIMING_TIMEFRAME_MODES = {
    "scalp": [],
    "intraday": [],
    "swing": [],
    "position": [],
}
WATCHLIST_STATUSES = {"READY", "WAIT"}
WATCHLIST_SIDES = {"LONG", "SHORT"}
WATCHLIST_PERMISSION_PRIORITY = {
    "LONG_ONLY": 0,
    "SHORT_ONLY": 0,
    "LONG_ALLOWED": 1,
    "SHORT_ALLOWED": 1,
    "WAIT": 3,
}
WATCHLIST_CACHE_TTL_SECONDS = 15.0
WATCHLIST_LATENCY_BUDGET = LatencyBudget(p50_ms=250.0, p95_ms=750.0, p99_ms=1500.0)
PHASE2_OPPORTUNITY_DECISION_VERSION = "phase2_opportunity_ledger_v1"
_watchlist_payload_cache = {}
_watchlist_cache_key_locks = {}
_watchlist_cache_guard = threading.Lock()
_MARKET_PARTICIPATION_UNSET = object()


@router.post(
    "/evaluate-frozen",
    response_model=FrozenDecisionEvaluationResponse,
)
def evaluate_frozen_signal_decision(payload: FrozenDecisionEvaluationRequest):
    """Evaluate an immutable context without reading mutable live state."""
    return evaluate_frozen_decision(
        payload.symbol,
        payload.timeframe,
        payload.intelligence,
        payload.derivatives,
        capital=payload.capital,
        risk_percent=payload.risk_percent,
    )


def build_multi_timeframe_signal_payload(
    db,
    symbol,
    mode=None,
    lower=None,
    middle=None,
    higher=None,
    stale_after_seconds=900,
    context=None,
):
    context = context or build_trade_prediction_context(
        db,
        symbol,
        mode,
        lower,
        middle,
        higher,
        stale_after_seconds,
    )
    stack = context.get("prediction_stack") or context.get("stack")
    timeframes = context.get("prediction_timeframes") or context.get("timeframes")
    confirmation = context["confirmation"]

    return {
        "symbol": symbol,
        "source": "multi_timeframe_confirmation",
        "mode": mode,
        "status": "OK",
        "data_scope": "timeframe_stack",
        "timeframes_used": stack,
        "prediction_stack": stack,
        "entry_stack": context.get("entry_stack") or [],
        "timeframes": timeframes,
        "confirmation": confirmation,
    }


def build_trade_setup_payload(
    db,
    symbol,
    mode=None,
    lower=None,
    middle=None,
    higher=None,
    stale_after_seconds=900,
    context=None,
):
    context = context or build_trade_prediction_context(
        db,
        symbol,
        mode,
        lower,
        middle,
        higher,
        stale_after_seconds,
    )
    stack = context.get("prediction_stack") or context.get("stack")
    timeframes = context.get("prediction_timeframes") or context.get("timeframes")
    confirmation = context["confirmation"]
    setup = build_trade_setup_decision(confirmation, timeframes)
    scenario = build_scenario_plan(confirmation, timeframes) if len(timeframes) >= 3 else None
    trade_plan = None
    validation = None

    if setup["status"] == "READY":
        entry_timeframe = setup.get("entry_timeframe") or stack[0]
        selected = _timeframe_record(timeframes, entry_timeframe)
        candle = _latest_candle(db, symbol, entry_timeframe)
        data = get_ai_inputs(db, symbol, entry_timeframe)
        current_price = float(candle.close_price)
        atr = _latest_atr(data["feature"], current_price)
        trade_plan = build_trade_plan(
            setup["side"],
            current_price,
            atr,
            confidence=_timeframe_confidence(selected, confirmation) or 0,
            symbol=symbol,
            timeframe=entry_timeframe,
        )
        if len(timeframes) >= 3:
            scenario = build_scenario_plan(
                confirmation,
                timeframes,
                trade_plan=trade_plan,
                current_price=current_price,
                atr=atr,
            )
        validation = validate_trade_plan_direction(
            setup["side"],
            trade_plan["entry"],
            trade_plan["target1"],
        )

        decision_snapshot = _persist_decision_snapshot_safe(
            db,
            build_decision_snapshot(
                symbol,
                entry_timeframe,
                decision=setup["status"],
                source_timestamp=candle.candle_time,
                effective_timestamp=candle.candle_time,
                confidence=_timeframe_confidence(selected, confirmation),
                regime=_timeframe_regime(selected, confirmation),
                signal=setup,
                trade_plan=trade_plan,
                context={
                    "mode": mode,
                    "timeframes_used": stack,
                    "confirmation": confirmation,
                    "scenario": scenario,
                    "trade_plan_validation": validation,
                },
            ),
        )

    return {
        "symbol": symbol,
        "source": "multi_timeframe_trade_setup",
        "mode": mode,
        "status": setup["status"],
        "data_scope": "timeframe_stack",
        "timeframes_used": stack,
        "prediction_stack": stack,
        "entry_stack": context.get("entry_stack") or [],
        "timing_stack": context.get("entry_stack") or [],
        "setup": setup,
        "confirmation": confirmation,
        "scenario": scenario,
        "trade_plan": trade_plan,
        "decision_snapshot": None if trade_plan is None else {
            "id": getattr(decision_snapshot, "id", None),
            "decision_version": getattr(decision_snapshot, "decision_version", None),
            "effective_timestamp": getattr(decision_snapshot, "effective_timestamp", None),
        },
        "trade_plan_validation": validation,
        "timeframes": timeframes,
    }


def build_entry_trigger_payload(
    db,
    symbol,
    mode=None,
    lower=None,
    middle=None,
    higher=None,
    stale_after_seconds=900,
    context=None,
):
    context = context or build_trade_prediction_context(
        db,
        symbol,
        mode,
        lower,
        middle,
        higher,
        stale_after_seconds,
    )
    stack = context.get("prediction_stack") or context.get("stack")
    timeframes = context.get("prediction_timeframes") or context.get("timeframes")
    confirmation = dict(context["confirmation"])
    confirmation.setdefault("prediction_stack", stack)
    confirmation.setdefault("entry_stack", context.get("entry_stack") or [])
    confirmation.setdefault("entry_timeframes", context.get("entry_timeframes") or [])
    trigger = build_entry_trigger_decision(confirmation, timeframes)
    # Scenario plans require the complete prediction stack.  Keep the
    # entry-trigger payload usable for partial/mocked contexts as well.
    scenario = (
        build_scenario_plan(confirmation, timeframes)
        if len(timeframes or []) >= 3
        else None
    )
    trade_plan = None
    validation = None

    if trigger["status"] == "READY":
        entry_timeframe = trigger.get("entry_timeframe") or stack[0]
        selected = _timeframe_record(timeframes, entry_timeframe)
        candle = _latest_candle(db, symbol, entry_timeframe)
        data = get_ai_inputs(db, symbol, entry_timeframe)
        current_price = float(candle.close_price)
        atr = _latest_atr(data["feature"], current_price)
        trade_plan = build_trade_plan(
            trigger["side"],
            current_price,
            atr,
            confidence=_timeframe_confidence(selected, confirmation) or 0,
            symbol=symbol,
            timeframe=entry_timeframe,
        )
        if len(timeframes or []) >= 3:
            scenario = build_scenario_plan(
                confirmation,
                timeframes,
                trade_plan=trade_plan,
                current_price=current_price,
                atr=atr,
            )
        validation = validate_trade_plan_direction(
            trigger["side"],
            trade_plan["entry"],
            trade_plan["target1"],
        )

        decision_snapshot = _persist_decision_snapshot_safe(
            db,
            build_decision_snapshot(
                symbol,
                entry_timeframe,
                decision=trigger["status"],
                source_timestamp=candle.candle_time,
                effective_timestamp=candle.candle_time,
                confidence=_timeframe_confidence(selected, confirmation),
                regime=_timeframe_regime(selected, confirmation),
                signal=trigger,
                trade_plan=trade_plan,
                context={
                    "mode": mode or _mode_from_stack(stack),
                    "timeframes_used": stack,
                    "confirmation": confirmation,
                    "scenario": scenario,
                    "trade_plan_validation": validation,
                },
            ),
        )

    return {
        "symbol": symbol,
        "source": "multi_timeframe_entry_trigger",
        "mode": mode or _mode_from_stack(stack),
        "status": trigger["status"],
        "data_scope": "timeframe_stack",
        "timeframes_used": stack,
        "prediction_stack": stack,
        "entry_stack": context.get("entry_stack") or [],
        "timing_stack": context.get("entry_stack") or [],
        "trigger": trigger,
        "confirmation": confirmation,
        "scenario": scenario,
        "trade_plan": trade_plan,
        "decision_snapshot": None if trade_plan is None else {
            "id": getattr(decision_snapshot, "id", None),
            "decision_version": getattr(decision_snapshot, "decision_version", None),
            "effective_timestamp": getattr(decision_snapshot, "effective_timestamp", None),
        },
        "trade_plan_validation": validation,
        "timeframes": timeframes,
    }


def build_multi_timeframe_context(
    db,
    symbol,
    mode=None,
    lower=None,
    middle=None,
    higher=None,
    stale_after_seconds=900,
):
    stack = _resolve_timeframe_stack(mode, lower, middle, higher)
    timeframes = [
        _build_signal_diagnostics(db, symbol, timeframe, stale_after_seconds)
        for timeframe in stack
    ]

    return {
        "stack": stack,
        "timeframes": timeframes,
        "confirmation": combine_timeframe_signals(timeframes),
    }


def build_trade_prediction_context(
    db,
    symbol,
    mode=None,
    lower=None,
    middle=None,
    higher=None,
    stale_after_seconds=900,
):
    prediction_stack = _resolve_prediction_timeframe_stack(mode, lower, middle, higher)
    entry_stack = _resolve_entry_timing_stack(mode)
    prediction_timeframes = [
        _build_signal_diagnostics(db, symbol, timeframe, stale_after_seconds)
        for timeframe in prediction_stack
    ]
    entry_timeframes = [
        _build_signal_diagnostics(db, symbol, timeframe, stale_after_seconds)
        for timeframe in entry_stack
    ]
    confirmation = combine_timeframe_signals(prediction_timeframes)
    confirmation = {
        **confirmation,
        "prediction_stack": prediction_stack,
        "entry_stack": entry_stack,
        "timing_stack": entry_stack,
        "entry_timeframes": entry_timeframes,
    }

    return {
        "stack": prediction_stack,
        "prediction_stack": prediction_stack,
        "timeframes": prediction_timeframes,
        "prediction_timeframes": prediction_timeframes,
        "entry_stack": entry_stack,
        "timing_stack": entry_stack,
        "entry_timeframes": entry_timeframes,
        "confirmation": confirmation,
    }


def _build_entry_trigger_payload(db, symbol, timeframes_to_use, stale_after_seconds):
    return build_entry_trigger_payload(
        db,
        symbol,
        stale_after_seconds=stale_after_seconds,
    )


def _resolve_prediction_timeframe_stack(mode=None, lower=None, middle=None, higher=None):
    explicit = [
        _normalize_timeframe_value(lower),
        _normalize_timeframe_value(middle),
        _normalize_timeframe_value(higher),
    ]
    if any(explicit) and explicit != ["1h", "4h", "1d"]:
        raise HTTPException(
            status_code=400,
            detail=(
                "The governed prediction stack is fixed to 1h, 2h, 4h, and 1d; "
                "custom timeframe stacks are not permitted"
            ),
        )
    stack = list(PREDICTION_TIMEFRAME_STACK)

    for timeframe in stack:
        if timeframe not in SUPPORTED_TIMEFRAMES:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported timeframe: {timeframe}",
            )

    if len(set(stack)) != 4:
        raise HTTPException(
            status_code=400,
            detail="The governed prediction stack must contain four distinct timeframes",
        )

    return stack


def _resolve_entry_timing_stack(mode=None):
    normalized_mode = _normalize_timeframe_value(mode)
    if normalized_mode in ENTRY_TIMING_TIMEFRAME_MODES:
        return list(ENTRY_TIMING_TIMEFRAME_MODES[normalized_mode])

    return []


def _get_cached_watchlist_payloads(db, stack, stale_after_seconds):
    key = (tuple(stack), int(stale_after_seconds))
    cached = _read_watchlist_cache(key)
    if cached is not None:
        return cached

    with _watchlist_cache_guard:
        key_lock = _watchlist_cache_key_locks.setdefault(key, threading.Lock())

    # Only one request computes a given timeframe stack at a time.
    with key_lock:
        cached = _read_watchlist_cache(key)
        if cached is not None:
            return cached

        symbols = SymbolRepository().get_active_symbols(db)
        payloads = [
            _build_entry_trigger_payload(
                db,
                item.symbol,
                stack,
                stale_after_seconds,
            )
            for item in symbols
        ]
        cached_at = time.monotonic()

        with _watchlist_cache_guard:
            _watchlist_payload_cache[key] = {
                "cached_at": cached_at,
                "payloads": copy.deepcopy(payloads),
            }

        return copy.deepcopy(payloads), _watchlist_cache_metadata(False, 0.0)


def _read_watchlist_cache(key):
    now = time.monotonic()

    with _watchlist_cache_guard:
        entry = _watchlist_payload_cache.get(key)
        if entry is None:
            return None

        age_seconds = max(0.0, now - entry["cached_at"])
        if age_seconds >= WATCHLIST_CACHE_TTL_SECONDS:
            _watchlist_payload_cache.pop(key, None)
            return None

        payloads = copy.deepcopy(entry["payloads"])

    return payloads, _watchlist_cache_metadata(True, age_seconds)


def _watchlist_cache_metadata(hit, age_seconds):
    return {
        "hit": hit,
        "age_seconds": round(age_seconds, 3),
        "ttl_seconds": int(WATCHLIST_CACHE_TTL_SECONDS),
    }


def _clear_watchlist_cache():
    with _watchlist_cache_guard:
        _watchlist_payload_cache.clear()
        _watchlist_cache_key_locks.clear()


def build_signal_watchlist_payload(
    db,
    mode=None,
    lower=None,
    middle=None,
    higher=None,
    status=None,
    side=None,
    failed_max=None,
    stale_after_seconds=900,
):
    stack = _resolve_prediction_timeframe_stack(mode, lower, middle, higher)
    payloads, cache = _get_cached_watchlist_payloads(
        db,
        stack,
        stale_after_seconds,
    )
    risk_rows = RiskRepository().latest_for_symbols(
        db,
        [payload["symbol"] for payload in payloads],
    )
    risk_payloads = {
        symbol: _watchlist_risk_payload(risk, stale_after_seconds)
        for symbol, risk in risk_rows.items()
    }
    participation_payloads = MarketParticipationRepository().latest_for_symbols(
        db,
        [payload["symbol"] for payload in payloads],
    )
    records = [
        _watchlist_row(
            payload,
            risk_payloads.get(payload["symbol"]),
            participation_payloads.get(payload["symbol"]),
        )
        for payload in payloads
    ]
    filtered_records, filters = _filter_watchlist(
        records,
        status,
        side,
        failed_max,
    )
    sorted_records = _sort_watchlist(filtered_records)

    return {
        "source": "signal_watchlist",
        "mode": mode,
        "timeframes": stack,
        "filters": filters,
        "sort": "priority",
        "count": len(sorted_records),
        "total_count": len(records),
        "summary": _summarize_watchlist(sorted_records),
        "records": sorted_records,
        "cache": cache,
    }


@router.get("/watchlist")
def get_signal_watchlist(
    mode: str | None = Query(default=None),
    lower: str | None = Query(default=None),
    middle: str | None = Query(default=None),
    higher: str | None = Query(default=None),
    status: str | None = Query(default=None),
    side: str | None = Query(default=None),
    failed_max: int | None = Query(default=None, ge=0),
    stale_after_seconds: int = Query(default=900, ge=1),
):
    db = SessionLocal()

    try:
        return build_signal_watchlist_payload(
            db,
            mode=mode,
            lower=lower,
            middle=middle,
            higher=higher,
            status=status,
            side=side,
            failed_max=failed_max,
            stale_after_seconds=stale_after_seconds,
        )

    finally:
        db.close()


@router.get("/watchlist/performance")
def get_watchlist_latency_baseline(
    mode: str | None = Query(default=None),
    lower: str | None = Query(default=None),
    middle: str | None = Query(default=None),
    higher: str | None = Query(default=None),
    stale_after_seconds: int = Query(default=900, ge=1),
    sample_size: int = Query(default=5, ge=1, le=20),
):
    db = SessionLocal()

    try:
        def _watchlist():
            return build_signal_watchlist_payload(
                db,
                mode=mode,
                lower=lower,
                middle=middle,
                higher=higher,
                status=None,
                side=None,
                failed_max=None,
                stale_after_seconds=stale_after_seconds,
            )

        report = build_stage_latency_report(
            {"watchlist": _watchlist},
            sample_size=sample_size,
            budgets={"watchlist": WATCHLIST_LATENCY_BUDGET},
        )
        return {
            "source": "watchlist_latency_baseline",
            "mode": mode,
            "timeframes": _resolve_timeframe_stack(mode, lower, middle, higher),
            "sample_size": report["sample_size"],
            "stage": report["stages"]["watchlist"],
        }
    finally:
        db.close()


@router.post("/watchlist/persist-ready")
def persist_ready_watchlist_setups(
    mode: str | None = Query(default=None),
    lower: str | None = Query(default=None),
    middle: str | None = Query(default=None),
    higher: str | None = Query(default=None),
    side: str | None = Query(default=None),
    stale_after_seconds: int = Query(default=900, ge=1),
):
    return persist_ready_watchlist_setups_for_stack(
        mode=mode,
        lower=lower,
        middle=middle,
        higher=higher,
        side=side,
        stale_after_seconds=stale_after_seconds,
    )


def persist_ready_watchlist_setups_for_stack(
    mode=None,
    lower=None,
    middle=None,
    higher=None,
    side=None,
    stale_after_seconds=900,
):
    db = SessionLocal()

    try:
        stack = _resolve_timeframe_stack(mode, lower, middle, higher)
        normalized_side = _normalize_watchlist_filter(side, WATCHLIST_SIDES, "side")
        payloads, cache = _get_cached_watchlist_payloads(
            db,
            stack,
            stale_after_seconds,
        )
        trade_repo = TradePlanRepository()
        participation_payloads = MarketParticipationRepository().latest_for_symbols(
            db,
            [payload["symbol"] for payload in payloads],
        )
        records = []

        for payload in payloads:
            opportunity_snapshot = _persist_phase2_opportunity_snapshot(db, payload)
            record = _persist_ready_watchlist_payload(
                db,
                trade_repo,
                payload,
                normalized_side,
                participation_payloads.get(payload["symbol"]),
            )
            record["opportunity_snapshot"] = opportunity_snapshot
            records.append(record)

        saved = [
            item
            for item in records
            if item["action"] == "saved"
        ]
        skipped = [
            item
            for item in records
            if item["action"] != "saved"
        ]

        return {
            "source": "watchlist_ready_trade_plan_persistence",
            "mode": mode,
            "timeframes": stack,
            "filters": {
                "side": normalized_side,
            },
            "total_count": len(records),
            "saved_count": len(saved),
            "skipped_count": len(skipped),
            "opportunity_snapshot_count": sum(
                1
                for item in records
                if (item.get("opportunity_snapshot") or {}).get("persisted")
            ),
            "saved": saved,
            "skipped": skipped,
            "cache": cache,
        }

    finally:
        db.close()


@router.post("/watchlist/recover-opportunity-gaps")
def recover_watchlist_opportunity_gaps(
    payload: dict = Body(...),
):
    """Reconstruct bounded, missed 1h evaluations from final candles only."""
    missing = list(payload.get("missing") or [])
    if not missing:
        return {
            "source": "phase2_opportunity_gap_recovery",
            "status": "NO_GAPS",
            "attempted_count": 0,
            "persisted_count": 0,
            "records": [],
        }
    if len(missing) > 48:
        raise HTTPException(status_code=400, detail="At most 48 hourly gaps may be recovered")

    db = SessionLocal()
    try:
        active_symbols = {
            item.symbol
            for item in SymbolRepository().get_active_symbols(db)
        }
        records = []
        for gap in missing:
            slot = _parse_opportunity_gap_timestamp(gap.get("effective_timestamp"))
            symbols = sorted(set(gap.get("symbols") or []))
            for symbol in symbols:
                if symbol not in active_symbols:
                    records.append(
                        {
                            "symbol": symbol,
                            "effective_timestamp": slot,
                            "persisted": False,
                            "reason": "inactive_symbol",
                        }
                    )
                    continue
                records.append(
                    _reconstruct_phase2_opportunity_snapshot(
                        db,
                        symbol,
                        slot,
                    )
                )

        persisted_count = sum(1 for item in records if item.get("persisted"))
        return {
            "source": "phase2_opportunity_gap_recovery",
            "status": "RECOVERED" if persisted_count == len(records) else "PARTIAL",
            "attempted_count": len(records),
            "persisted_count": persisted_count,
            "records": records,
        }
    finally:
        db.close()


@router.get("/batch", response_model=SignalBatchResponse)
def get_signal_batch(
    symbols: str | None = Query(default=None),
    timeframe: str = Query(default="5m", enum=["1m", "5m", "15m", "1h", "2h", "4h", "1d"]),
    stale_after_seconds: int = Query(default=900, ge=1),
):
    db = SessionLocal()

    try:
        requested_symbols = _normalize_signal_batch_symbols(symbols)
        if not requested_symbols:
            requested_symbols = [
                item.symbol
                for item in SymbolRepository().get_active_symbols(db)
            ]

        return build_signal_batch_payload(
            db,
            requested_symbols,
            timeframe,
            stale_after_seconds,
        )

    finally:
        db.close()


@router.get("/{symbol}/multi-timeframe", response_model=SymbolContextResponse)
def get_multi_timeframe_signal(
    symbol: str,
    mode: str | None = Query(default=None),
    lower: str | None = Query(default=None),
    middle: str | None = Query(default=None),
    higher: str | None = Query(default=None),
    stale_after_seconds: int = Query(default=900, ge=1),
):
    db = SessionLocal()

    try:
        return build_multi_timeframe_signal_payload(
            db,
            symbol,
            mode=mode,
            lower=lower,
            middle=middle,
            higher=higher,
            stale_after_seconds=stale_after_seconds,
        )

    finally:
        db.close()


@router.get("/{symbol}/trade-setup", response_model=SymbolContextResponse)
def get_trade_setup(
    symbol: str,
    mode: str | None = Query(default=None),
    lower: str | None = Query(default=None),
    middle: str | None = Query(default=None),
    higher: str | None = Query(default=None),
    stale_after_seconds: int = Query(default=900, ge=1),
):
    db = SessionLocal()

    try:
        return build_trade_setup_payload(
            db,
            symbol,
            mode=mode,
            lower=lower,
            middle=middle,
            higher=higher,
            stale_after_seconds=stale_after_seconds,
        )

    finally:
        db.close()


@router.get("/{symbol}/scenario", response_model=SymbolContextResponse)
def get_scenario(
    symbol: str,
    mode: str | None = Query(default=None),
    lower: str | None = Query(default=None),
    middle: str | None = Query(default=None),
    higher: str | None = Query(default=None),
    stale_after_seconds: int = Query(default=900, ge=1),
):
    db = SessionLocal()

    try:
        stack = _resolve_timeframe_stack(mode, lower, middle, higher)
        timeframes = [
            _build_signal_diagnostics(db, symbol, timeframe, stale_after_seconds)
            for timeframe in stack
        ]
        confirmation = combine_timeframe_signals(timeframes)
        scenario = build_scenario_plan(confirmation, timeframes)

        return {
            "symbol": symbol,
            "source": "scenario_engine",
            "mode": mode,
            "timeframes_used": stack,
            "timeframes": timeframes,
            "confirmation": confirmation,
            "scenario": scenario,
        }

    finally:
        db.close()


@router.get("/{symbol}/contradiction", response_model=SymbolContextResponse)
def get_contradiction(
    symbol: str,
    timeframe: str = Query(default="5m", enum=["1m", "5m", "15m", "1h", "2h", "4h", "1d"]),
    stale_after_seconds: int = Query(default=900, ge=1),
):
    db = SessionLocal()

    try:
        freshness_window = stale_after_seconds_for_timeframe(
            timeframe,
            fallback=stale_after_seconds,
        )
        return build_contradiction_report(db, symbol, timeframe, freshness_window)

    finally:
        db.close()


@router.get("/{symbol}/probability", response_model=SymbolContextResponse)
def get_probability(
    symbol: str,
    timeframe: str = Query(default="5m", enum=["1m", "5m", "15m", "1h", "2h", "4h", "1d"]),
    stale_after_seconds: int = Query(default=900, ge=1),
):
    db = SessionLocal()

    try:
        freshness_window = stale_after_seconds_for_timeframe(
            timeframe,
            fallback=stale_after_seconds,
        )
        return build_probability_profile(db, symbol, timeframe, freshness_window)

    finally:
        db.close()


@router.get("/{symbol}/data-quality")
def get_data_quality(
    symbol: str,
    timeframe: str = Query(default="5m", enum=["1m", "5m", "15m", "1h", "2h", "4h", "1d"]),
    stale_after_seconds: int = Query(default=900, ge=1),
    limit: int = Query(default=20, ge=2, le=100),
    persist: bool = Query(default=True),
):
    db = SessionLocal()

    try:
        return build_data_quality_observability(
            db,
            symbol.upper(),
            timeframe=timeframe,
            stale_after_seconds=stale_after_seconds,
            limit=limit,
            persist=persist,
        )

    finally:
        db.close()


@router.get("/{symbol}/data-quality/ledger")
def get_data_quality_ledger(
    symbol: str,
    timeframe: str | None = Query(default=None, enum=["1m", "5m", "15m", "1h", "2h", "4h", "1d"]),
    limit: int = Query(default=100, ge=1, le=500),
):
    db = SessionLocal()

    try:
        records = DataQualityEventRepository().list_events(
            db,
            symbol=symbol.upper(),
            timeframe=timeframe,
            limit=limit,
        )
        blocked = [item for item in records if item["blocked"]]
        by_category = {}
        for item in records:
            by_category[item["category"]] = by_category.get(item["category"], 0) + 1

        return {
            "source": "data_quality_ledger_history",
            "symbol_filter": symbol.upper(),
            "timeframe_filter": timeframe,
            "count": len(records),
            "blocked_count": len(blocked),
            "summary": {
                "by_category": dict(sorted(by_category.items())),
            },
            "records": records,
        }

    finally:
        db.close()


@router.get("/{symbol}/entry-trigger", response_model=SymbolContextResponse)
def get_entry_trigger(
    symbol: str,
    mode: str | None = Query(default=None),
    lower: str | None = Query(default=None),
    middle: str | None = Query(default=None),
    higher: str | None = Query(default=None),
    stale_after_seconds: int = Query(default=900, ge=1),
):
    db = SessionLocal()

    try:
        return build_entry_trigger_payload(
            db,
            symbol,
            mode=mode,
            lower=lower,
            middle=middle,
            higher=higher,
            stale_after_seconds=stale_after_seconds,
        )

    finally:
        db.close()


@router.get("/{symbol}/diagnostics", response_model=SymbolContextResponse)
def get_signal_diagnostics(
    symbol: str,
    timeframe: str = Query(default="5m", enum=["1m", "5m", "15m", "1h", "2h", "4h", "1d"]),
    stale_after_seconds: int = Query(default=900, ge=1),
):
    db = SessionLocal()

    try:
        return build_signal_diagnostics_payload(db, symbol, timeframe, stale_after_seconds)

    finally:
        db.close()


def build_signal_diagnostics_payload(db, symbol, timeframe="5m", stale_after_seconds=900):
    return _build_signal_diagnostics(db, symbol, timeframe, stale_after_seconds)


def _probability_aliases(probability):
    if not probability:
        return {
            "long_probability": None,
            "short_probability": None,
            "wait_probability": None,
            "probabilities": {"LONG": 0, "SHORT": 0, "WAIT": 100},
            "probability_decision": "WAIT",
            "probability_actionable": False,
            "probability_status": "INVALIDATED",
        }

    return {
        "long_probability": probability.get("long_probability"),
        "short_probability": probability.get("short_probability"),
        "wait_probability": probability.get("wait_probability"),
        "probabilities": probability.get("probabilities") or {},
        "probability_decision": probability.get("decision"),
        "probability_actionable": probability.get("actionable"),
        "probability_status": probability.get("status"),
    }


def _persist_decision_snapshot_safe(db, snapshot):
    try:
        return persist_decision_snapshot(db, snapshot)
    except Exception:
        safe_rollback(db)
        return None


def build_signal_payload(db, symbol, timeframe="5m", stale_after_seconds=900):
    freshness_window = stale_after_seconds_for_timeframe(
        timeframe,
        fallback=stale_after_seconds,
    )
    candle = _latest_candle(db, symbol, timeframe)

    if not candle:
        probability = build_probability_profile(
            db,
            symbol,
            timeframe,
            freshness_window,
        )
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "source": "computed_current",
            "status": "NO_DATA",
            "data_scope": "timeframe",
            "signal": "NO_DATA",
            "confidence": 0,
            "scoring_profile": None,
            "freshness": freshness_status(None, freshness_window),
            "message": "No latest candle found for symbol/timeframe",
            "contradiction": build_contradiction_report(db, symbol, timeframe, freshness_window),
            "probability": probability,
            **_probability_aliases(probability),
        }

    data = get_ai_inputs(db, symbol, timeframe)
    signal = generate_master_signal(data["feature"], data["regime"], data["orderflow"], data["smc"])

    current_price = float(candle.close_price)
    atr = _latest_atr(data["feature"], current_price)
    trade_plan = build_trade_plan(
        signal["signal"],
        current_price,
        atr,
        confidence=signal["confidence"],
        symbol=symbol,
        timeframe=timeframe,
    )
    decision_snapshot = _persist_decision_snapshot_safe(
        db,
        build_decision_snapshot(
            symbol,
            timeframe,
            decision=signal["signal"],
            source_timestamp=candle.candle_time,
            effective_timestamp=candle.candle_time,
            confidence=signal["confidence"],
            regime=getattr(data["regime"], "Regime", None) or getattr(data["regime"], "regime", None),
            signal={
                "signal": signal["signal"],
                "bias": signal["bias"],
                "confidence": signal["confidence"],
                "score": signal["score"],
                "reasons": signal["reasons"],
            },
            trade_plan=trade_plan,
            context={
                "feature": getattr(data["feature"], "Id", None) or getattr(data["feature"], "id", None),
                "regime": getattr(data["regime"], "Id", None) or getattr(data["regime"], "id", None),
                "orderflow": getattr(data["orderflow"], "Id", None) or getattr(data["orderflow"], "id", None),
                "smc": getattr(data["smc"], "id", None),
            },
        ),
    )
    probability = build_probability_profile(db, symbol, timeframe, freshness_window)

    try:
        persisted_signal = _latest_persisted_signal(
            db,
            symbol,
            timeframe,
            stale_after_seconds,
        )
    except Exception:
        safe_rollback(db)
        persisted_signal = {
            "latest_usable": None,
            "latest_ignored": None,
        }

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "source": "computed_current",
        "status": "OK",
        "data_scope": "timeframe",
        "signal": signal["signal"],
        "bias": signal["bias"],
        "confidence": signal["confidence"],
        "score": signal["score"],
        "scoring_profile": signal.get("scoring_profile"),
        "current_price": current_price,
        "candle_time": candle.candle_time,
        "freshness": freshness_status(
            candle_freshness_timestamp(candle),
            freshness_window,
        ),
        "trade_plan": trade_plan,
        "decision_snapshot": {
            "id": getattr(decision_snapshot, "id", None),
            "decision_version": getattr(decision_snapshot, "decision_version", None),
            "effective_timestamp": getattr(decision_snapshot, "effective_timestamp", None),
        },
        "reasons": signal["reasons"],
        "contradiction": build_contradiction_report(db, symbol, timeframe, freshness_window),
        "probability": probability,
        **_probability_aliases(probability),
        "inputs": {
            "feature": freshness_status(
                getattr(data["feature"], "CreatedAt", None),
                freshness_window,
            ),
            "regime": freshness_status(
                getattr(data["regime"], "CreatedAt", None),
                freshness_window,
            ),
            "orderflow": freshness_status(
                getattr(data["orderflow"], "CreatedAt", None),
                freshness_window,
            ),
            "smc": freshness_status(
                getattr(data["smc"], "created_at", None),
                freshness_window,
            ),
        },
        "latest_persisted_signal": persisted_signal["latest_usable"],
        "ignored_persisted_signal": persisted_signal["latest_ignored"],
    }


def build_signal_batch_payload(db, symbols, timeframe="5m", stale_after_seconds=900):
    normalized_symbols = _normalize_signal_batch_symbols(symbols)
    records = [
        build_signal_payload(db, symbol, timeframe, stale_after_seconds)
        for symbol in normalized_symbols
    ]

    return {
        "source": "computed_current_batch",
        "status": "OK",
        "data_scope": "timeframe",
        "timeframe": timeframe,
        "count": len(records),
        "records": records,
        "records_by_symbol": {
            record["symbol"]: record
            for record in records
        },
    }


@router.get("/{symbol}", response_model=SignalResponse)
def get_signal(
    symbol: str,
    timeframe: str = Query(default="5m", enum=["1m", "5m", "15m", "1h", "2h", "4h", "1d"]),
    stale_after_seconds: int = Query(default=900, ge=1),
):
    db = SessionLocal()

    try:
        return build_signal_payload(db, symbol, timeframe, stale_after_seconds)

    finally:
        db.close()


def _latest_candle(db, symbol, timeframe):
    return get_latest_candle(db, symbol, timeframe)


def _normalize_signal_batch_symbols(symbols):
    values = symbols.split(",") if isinstance(symbols, str) else symbols or []
    normalized = []

    for value in values:
        symbol = str(value or "").strip().upper()
        if symbol and symbol not in normalized:
            normalized.append(symbol)

    if len(normalized) > 50:
        raise HTTPException(status_code=400, detail="A maximum of 50 symbols is supported")

    return normalized


def _resolve_timeframe_stack(mode=None, lower=None, middle=None, higher=None):
    stack = _timeframe_stack_from_mode(mode)
    explicit = [_normalize_timeframe_value(lower), _normalize_timeframe_value(middle), _normalize_timeframe_value(higher)]

    if any(explicit) and explicit != ["1h", "4h", "1d"]:
        raise HTTPException(
            status_code=400,
            detail=(
                "The governed prediction stack is fixed to 1h, 2h, 4h, and 1d; "
                "custom timeframe stacks are not permitted"
            ),
        )

    for timeframe in stack:
        if timeframe not in SUPPORTED_TIMEFRAMES:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported timeframe: {timeframe}",
            )

    if len(set(stack)) != 4:
        raise HTTPException(
            status_code=400,
            detail="The governed prediction stack must contain four distinct timeframes",
        )

    return stack


def _timeframe_stack_from_mode(mode):
    normalized_mode = _normalize_timeframe_value(mode)

    if normalized_mode is None:
        return list(DEFAULT_TIMEFRAME_STACK)

    if normalized_mode not in TIMEFRAME_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported mode: {mode}",
        )

    return list(TIMEFRAME_MODES[normalized_mode])


def _mode_from_stack(stack):
    for mode, configured_stack in TIMEFRAME_MODES.items():
        if list(stack) == list(configured_stack):
            return mode
    return "custom"


def _normalize_timeframe_value(value):
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    normalized = text.lower()
    if "annotation=" in normalized and "alias=" in normalized:
        return None
    if normalized.startswith("query("):
        return None

    return normalized


def _filter_watchlist(records, status=None, side=None, failed_max=None):
    normalized_status = _normalize_watchlist_filter(
        status,
        WATCHLIST_STATUSES,
        "status",
    )
    normalized_side = _normalize_watchlist_filter(
        side,
        WATCHLIST_SIDES,
        "side",
    )
    filtered = records

    if normalized_status:
        filtered = [
            item
            for item in filtered
            if item["status"] == normalized_status
        ]

    if normalized_side:
        filtered = [
            item
            for item in filtered
            if item["side"] == normalized_side
        ]

    if failed_max is not None:
        filtered = [
            item
            for item in filtered
            if len(item.get("failed_conditions") or []) <= failed_max
        ]

    return filtered, {
        "status": normalized_status,
        "side": normalized_side,
        "failed_max": failed_max,
    }


def _normalize_watchlist_filter(value, allowed_values, field_name):
    if value is None:
        return None

    normalized = value.upper()

    if normalized not in allowed_values:
        allowed = ", ".join(sorted(allowed_values))
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported watchlist {field_name}: {value}. Allowed: {allowed}",
        )

    return normalized


def _sort_watchlist(records):
    return sorted(records, key=_watchlist_priority_key)


def _summarize_watchlist(records):
    summary = {
        "ready": 0,
        "wait": 0,
        "long": 0,
        "short": 0,
        "no_side": 0,
    }

    for item in records:
        status = item.get("status")
        side = item.get("side")

        if status == "READY":
            summary["ready"] += 1
        elif status == "WAIT":
            summary["wait"] += 1

        if side == "LONG":
            summary["long"] += 1
        elif side == "SHORT":
            summary["short"] += 1
        else:
            summary["no_side"] += 1

    return summary


def _watchlist_priority_key(item):
    status_priority = {
        "READY": 0,
        "WAIT": 1,
    }.get(item["status"], 2)
    failed_count = len(item.get("failed_conditions") or [])
    permission_priority = WATCHLIST_PERMISSION_PRIORITY.get(
        item.get("trade_permission"),
        2,
    )
    side_priority = 0 if item.get("side") in WATCHLIST_SIDES else 1
    score = abs(
        item.get("entry_score")
        or item.get("score_1h")
        or item.get("score_2h")
        or item.get("score_4h")
        or item.get("score_1d")
        or item.get("score_15m")
        or item.get("score_5m")
        or 0
    )

    return (
        status_priority,
        failed_count,
        permission_priority,
        side_priority,
        -score,
        item["symbol"],
    )


def _persist_ready_watchlist_payload(
    db,
    trade_repo,
    payload,
    side_filter=None,
    market_participation=_MARKET_PARTICIPATION_UNSET,
):
    symbol = payload["symbol"]
    trigger = payload["trigger"]
    side = trigger["side"]
    trade_plan = payload["trade_plan"]
    validation = payload["trade_plan_validation"]
    selected = _selected_timeframe_record(payload)
    confidence = _timeframe_confidence(selected, payload.get("confirmation"))

    base = {
        "symbol": symbol,
        "status": trigger["status"],
        "side": side,
        "reason": trigger["reason"],
    }

    if side_filter and side != side_filter:
        return {
            **base,
            "action": "skipped_side_filter",
            "message": f"Side does not match filter: {side_filter}",
        }

    if trigger["status"] != "READY":
        return {
            **base,
            "action": "skipped_not_ready",
            "failed_conditions": [
                item["name"]
                for item in trigger.get("conditions", [])
                if not item["passed"]
            ],
        }

    if market_participation is not _MARKET_PARTICIPATION_UNSET:
        participation = evaluate_market_participation(market_participation, side)
        if not participation["allowed"]:
            return {
                **base,
                "action": "skipped_market_participation",
                "message": participation["reason"],
                "market_participation": participation,
            }

    if not trade_plan:
        return {
            **base,
            "action": "skipped_missing_trade_plan",
            "message": "READY trigger did not produce a trade plan",
        }

    if not validation or not validation["is_valid"]:
        return {
            **base,
            "action": "skipped_invalid_trade_plan",
            "validation_errors": validation["errors"] if validation else [],
        }

    if hasattr(db, "query") and PaperTradeRepository().has_open_trade(db, symbol):
        return {
            **base,
            "action": "skipped_active_symbol_trade",
            "message": "An active paper trade already holds the symbol lock",
        }

    replaced_trade_plan_id = None
    get_open_trade = getattr(trade_repo, "get_open_trade", None)
    if callable(get_open_trade):
        existing_trade = get_open_trade(db, symbol, side)
    else:
        existing_trade = None
        if trade_repo.has_open_trade(db, symbol, side):
            return {
                **base,
                "action": "skipped_existing_open",
                "message": "Open trade plan already exists for symbol and side",
            }
    if existing_trade:
        if _trade_plan_matches_existing_trade(
            existing_trade,
            trade_plan,
            confidence=confidence or 0,
        ):
            return {
                **base,
                "action": "skipped_existing_open",
                "message": "Open trade plan already exists for symbol and side",
            }

        replaced_trade_plan_id = existing_trade.id
        trade_repo.invalidate_trade(
            db,
            existing_trade,
            reason="Open trade plan replaced by newer READY signal",
        )

    trade = trade_repo.save_ready_trade_plan(
        db,
        symbol,
        side,
        trade_plan,
        confidence or 0,
        context={
            "mode": payload.get("mode"),
            "entry_timeframe": selected.get("timeframe"),
            "timeframe_stack": payload.get("timeframes_used"),
            "scenario": payload.get("scenario"),
            "contradiction": (payload.get("confirmation") or {}).get("contradiction"),
            "regime": (
                selected.get("component_scores", {})
                .get("regime", {})
                .get("value")
            ),
        },
    )

    return {
        **base,
        "action": "replaced_existing_open" if replaced_trade_plan_id else "saved",
        "replaced_trade_plan_id": replaced_trade_plan_id,
        "trade_plan_id": trade.id,
        "entry_price": trade.entry_price,
        "stop_loss": trade.stop_loss,
        "target1": trade.target1,
        "target2": trade.target2,
        "risk_reward": trade.risk_reward,
        "confidence": trade.confidence,
    }


def _persist_phase2_opportunity_snapshot(db, payload):
    timeframes = payload.get("timeframes") or []
    selected = _selected_timeframe_record(payload)
    source_timestamp = selected.get("candle_time")
    timeframe = selected.get("timeframe")

    if not source_timestamp or not timeframe:
        return {
            "persisted": False,
            "reason": "missing_entry_timeframe_candle",
        }

    trigger = payload.get("trigger") or {}
    confirmation = payload.get("confirmation") or {}
    conditions = trigger.get("conditions") or []
    quality_state = (
        "OK"
        if all(item.get("status") == "OK" for item in timeframes)
        else "DEGRADED"
    )
    snapshot = build_decision_snapshot(
        payload["symbol"],
        timeframe,
        decision=trigger.get("status") or "WAIT",
        source_timestamp=source_timestamp,
        effective_timestamp=source_timestamp,
        quality_state=quality_state,
        confidence=(
            selected.get("confidence")
            if selected.get("confidence") is not None
            else trigger.get("stack_confidence")
        ),
        regime=_timeframe_regime(selected, confirmation),
        signal=trigger,
        trade_plan=payload.get("trade_plan"),
        context={
            "audit_scope": "PHASE2_FUTURES_OPPORTUNITY",
            "market": "FUTURES",
            "mode": payload.get("mode"),
            "timeframes_used": payload.get("timeframes_used"),
            "timeframe_candles": {
                item.get("timeframe"): item.get("candle_time")
                for item in timeframes
                if item.get("timeframe")
            },
            "confirmation": confirmation,
            "scenario": payload.get("scenario"),
            "trade_plan_validation": payload.get("trade_plan_validation"),
            "trigger_reason": trigger.get("reason"),
            "failed_conditions": [
                item.get("name")
                for item in conditions
                if not item.get("passed")
            ],
            "opportunity_recovery": payload.get("opportunity_recovery"),
        },
    )
    snapshot["decision_version"] = PHASE2_OPPORTUNITY_DECISION_VERSION
    record = _persist_decision_snapshot_safe(db, snapshot)

    return {
        "persisted": record is not None,
        "id": getattr(record, "id", None),
        "decision_version": getattr(record, "decision_version", None),
        "effective_timestamp": getattr(record, "effective_timestamp", None),
    }


def _parse_opportunity_gap_timestamp(value):
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid opportunity gap timestamp: {value}",
            ) from exc
    else:
        raise HTTPException(status_code=400, detail="Gap effective_timestamp is required")

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed.replace(minute=0, second=0, microsecond=0)


def _reconstruct_phase2_opportunity_snapshot(db, symbol, slot):
    evaluation_cutoff = slot + timedelta(hours=1)
    candles_by_timeframe = {
        timeframe: get_candles_as_of(
            db,
            symbol,
            timeframe,
            evaluation_cutoff,
            limit=300,
        )
        for timeframe in PREDICTION_TIMEFRAME_STACK
    }
    stack = build_point_in_time_stack(
        symbol,
        candles_by_timeframe,
        evaluation_cutoff,
        intelligence_builder=build_candle_intelligence_as_of,
        history_limit=300,
        minimum_history=50,
    )
    if stack.get("status") != "READY":
        return {
            "symbol": symbol,
            "effective_timestamp": slot,
            "persisted": False,
            "reason": "insufficient_point_in_time_history",
            "timeframes": [
                {
                    "timeframe": item.get("timeframe"),
                    "candle_count": item.get("candle_count"),
                    "required_candle_count": item.get("required_candle_count"),
                }
                for item in stack.get("timeframes") or []
            ],
        }

    timeframes = [
        _reconstructed_signal_diagnostics(item)
        for item in stack["timeframes"]
    ]
    confirmation = combine_timeframe_signals(timeframes)
    confirmation = {
        **confirmation,
        "prediction_stack": list(PREDICTION_TIMEFRAME_STACK),
        "entry_stack": [],
        "timing_stack": [],
        "entry_timeframes": [],
    }
    trigger = build_entry_trigger_decision(confirmation, timeframes)
    payload = {
        "symbol": symbol,
        "mode": "intraday",
        "timeframes_used": list(PREDICTION_TIMEFRAME_STACK),
        "timeframes": timeframes,
        "confirmation": confirmation,
        "trigger": trigger,
        "scenario": build_scenario_plan(confirmation, timeframes),
        "trade_plan": None,
        "trade_plan_validation": None,
        "opportunity_recovery": {
            "method": "POINT_IN_TIME_FINAL_CANDLE_RECONSTRUCTION",
            "evaluation_cutoff": evaluation_cutoff,
            "leakage_status": "PASS",
        },
    }
    result = _persist_phase2_opportunity_snapshot(db, payload)
    return {
        "symbol": symbol,
        "effective_timestamp": slot,
        **result,
        "decision": trigger.get("status"),
        "reason": trigger.get("reason"),
    }


def _reconstructed_signal_diagnostics(item):
    intelligence = item.get("intelligence") or {}
    feature = intelligence.get("feature") or {}
    regime = intelligence.get("regime") or {}
    orderflow = intelligence.get("orderflow") or {}
    smc = intelligence.get("smc") or {}
    orderflow_row = SimpleNamespace(**orderflow)
    orderflow_row.FlowSignal = orderflow.get("signal")
    smc_row = SimpleNamespace(**smc)
    smc_row.smc_bias = smc.get("bias")
    components = score_master_signal_components(
        SimpleNamespace(**feature),
        SimpleNamespace(**regime),
        orderflow_row,
        smc_row,
    )
    return {
        "symbol": item.get("symbol"),
        "timeframe": item.get("timeframe"),
        "source": "point_in_time_gap_recovery",
        "status": item.get("status"),
        "data_scope": "timeframe",
        "signal": item.get("signal"),
        "bias": item.get("bias"),
        "confidence": item.get("confidence"),
        "score": item.get("score"),
        "current_price": intelligence.get("current_price"),
        "candle_time": item.get("last_candle_time"),
        "freshness": {
            "status": "HISTORICAL_RECONSTRUCTED",
            "is_stale": False,
        },
        "component_scores": components,
        "reasons": (intelligence.get("signal") or {}).get("reasons") or [],
        "inputs": {
            key: {
                "status": "HISTORICAL_RECONSTRUCTED",
                "is_stale": False,
            }
            for key in ("feature", "regime", "orderflow", "smc")
        },
    }


def _trade_plan_matches_existing_trade(existing_trade, trade_plan, confidence=None):
    return (
        _same_optional_number(getattr(existing_trade, "entry_price", None), trade_plan.get("entry"))
        and _same_optional_number(getattr(existing_trade, "stop_loss", None), trade_plan.get("stop_loss"))
        and _same_optional_number(getattr(existing_trade, "target1", None), trade_plan.get("target1"))
        and _same_optional_number(getattr(existing_trade, "target2", None), trade_plan.get("target2"))
        and _same_optional_number(getattr(existing_trade, "risk_reward", None), trade_plan.get("risk_reward"))
        and _same_optional_number(getattr(existing_trade, "confidence", None), confidence)
    )


def _same_optional_number(left, right, tolerance=1e-8):
    if left is None and right is None:
        return True

    if left is None or right is None:
        return False

    return abs(float(left) - float(right)) <= tolerance


def _watchlist_row(
    payload,
    risk=None,
    market_participation=_MARKET_PARTICIPATION_UNSET,
):
    timeframes = {
        item["timeframe"]: item
        for item in payload["timeframes"]
    }
    selected = _selected_timeframe_record(payload)
    entry_timeframe = selected.get("timeframe")
    trade_plan = payload["trade_plan"] or {}
    trigger = payload["trigger"]
    confirmation = payload["confirmation"]
    computed_risk = _watchlist_computed_risk_payload(payload)
    participation_payload = (
        None
        if market_participation is _MARKET_PARTICIPATION_UNSET
        else market_participation
    )
    participation = evaluate_market_participation(
        participation_payload,
        trigger.get("side"),
    )
    eligibility = _watchlist_eligibility(
        payload,
        risk,
        computed_risk,
        participation
        if market_participation is not _MARKET_PARTICIPATION_UNSET
        else None,
    )
    risk_source = "persisted" if risk else "computed" if computed_risk else "trigger"

    return {
        "symbol": payload["symbol"],
        "status": trigger["status"],
        "side": trigger["side"],
        "overall_bias": confirmation["overall_bias"],
        "trade_permission": confirmation["trade_permission"],
        "reason": trigger["reason"],
        "confidence": _timeframe_confidence(selected, confirmation),
        "stack_confidence": trigger.get("stack_confidence"),
        "confidence_window": trigger.get("confidence_window"),
        "failed_conditions": [
            item["name"]
            for item in trigger.get("conditions", [])
            if not item["passed"]
        ],
        "validation_errors": (
            payload.get("trade_plan_validation", {}).get("errors", [])
            if payload.get("trade_plan_validation")
            else []
        ),
        "eligibility_label": eligibility["label"],
        "eligibility_tone": eligibility["tone"],
        "eligibility_reason": eligibility["reason"],
        "eligibility_allowed": eligibility["allowed"],
        "eligibility_status": eligibility["status"],
        "market_participation": participation,
        "combined_execution": {
            "allowed": eligibility["allowed"],
            "status": eligibility["status"],
            "reason": eligibility["reason"],
            "selected_timeframe": entry_timeframe,
            "side": trigger.get("side"),
            "score": _timeframe_value(timeframes, entry_timeframe, "score"),
            "confidence": _timeframe_confidence(selected, confirmation),
            "market_participation_status": participation["status"],
        },
        "risk_source": risk_source,
        "persisted_risk": risk,
        "computed_risk": computed_risk,
        "risk_decision": None if not risk else risk.get("decision"),
        "risk_status": None if not risk else risk.get("status"),
        "risk_is_usable": None if not risk else risk.get("is_usable"),
        "risk_reason": None if not risk else risk.get("reason"),
        "risk_validation_errors": [] if not risk else (risk.get("validation_errors") or []),
        "entry_timeframe": entry_timeframe,
        "entry_bias": _timeframe_value(timeframes, entry_timeframe, "bias"),
        "entry_score": _timeframe_value(timeframes, entry_timeframe, "score"),
        "bias_5m": _timeframe_value(timeframes, "5m", "bias"),
        "bias_15m": _timeframe_value(timeframes, "15m", "bias"),
        "bias_1h": _timeframe_value(timeframes, "1h", "bias"),
        "bias_2h": _timeframe_value(timeframes, "2h", "bias"),
        "bias_4h": _timeframe_value(timeframes, "4h", "bias"),
        "bias_1d": _timeframe_value(timeframes, "1d", "bias"),
        "score_5m": _timeframe_value(timeframes, "5m", "score"),
        "score_15m": _timeframe_value(timeframes, "15m", "score"),
        "score_1h": _timeframe_value(timeframes, "1h", "score"),
        "score_2h": _timeframe_value(timeframes, "2h", "score"),
        "score_4h": _timeframe_value(timeframes, "4h", "score"),
        "score_1d": _timeframe_value(timeframes, "1d", "score"),
        "entry": trade_plan.get("entry"),
        "stop_loss": trade_plan.get("stop_loss"),
        "target1": trade_plan.get("target1"),
        "target2": trade_plan.get("target2"),
        "risk_reward": trade_plan.get("risk_reward"),
        "price_precision": trade_plan.get("price_precision"),
    }


def _watchlist_eligibility(
    payload,
    risk=None,
    computed_risk=None,
    market_participation=None,
):
    trigger = payload["trigger"] or {}
    trade_plan = payload.get("trade_plan") or {}
    validation = payload.get("trade_plan_validation") or {}
    failed_conditions = [
        item.get("name")
        for item in trigger.get("conditions", [])
        if not item.get("passed")
    ]

    if trigger.get("status") != "READY":
        if "confidence_window" in failed_conditions:
            return {
                "label": "Blocked by confidence",
                "tone": "amber",
                "reason": trigger.get("reason") or "Confidence is outside the entry window",
                "allowed": False,
                "status": "BLOCKED_CONFIDENCE",
            }

        return {
            "label": "Blocked",
            "tone": "rose",
            "reason": trigger.get("reason") or "Entry trigger is not ready",
            "allowed": False,
            "status": "BLOCKED_SIGNAL",
        }

    if market_participation and not market_participation.get("allowed"):
        return {
            "label": "Blocked by participation",
            "tone": "rose",
            "reason": market_participation.get("reason") or "Spot participation does not confirm the signal",
            "allowed": False,
            "status": "BLOCKED_PARTICIPATION",
        }

    if risk and risk.get("is_usable") is False:
        return {
            "label": "Blocked by risk",
            "tone": "rose",
            "reason": risk.get("reason") or "Persisted risk decision is not usable",
            "allowed": False,
            "status": "BLOCKED_RISK",
        }

    if risk and risk.get("is_usable") is True:
        return {
            "label": "Eligible",
            "tone": "emerald",
            "reason": risk.get("reason") or "Persisted risk decision approved",
            "allowed": True,
            "status": "ELIGIBLE",
        }

    if computed_risk and computed_risk.get("is_usable") is False:
        return {
            "label": "Blocked by risk",
            "tone": "rose",
            "reason": computed_risk.get("reason") or "Computed risk decision is not usable",
            "allowed": False,
            "status": "BLOCKED_RISK",
        }

    if computed_risk and computed_risk.get("is_usable") is True:
        return {
            "label": "Eligible",
            "tone": "emerald",
            "reason": computed_risk.get("reason") or "Computed risk decision approved",
            "allowed": True,
            "status": "ELIGIBLE",
        }

    if validation and not validation.get("is_valid", True):
        errors = validation.get("errors") or []
        return {
            "label": "Blocked by risk",
            "tone": "rose",
            "reason": ", ".join(errors) if errors else "Trade plan validation failed",
            "allowed": False,
            "status": "BLOCKED_RISK",
        }

    risk_reward = trade_plan.get("risk_reward")
    if risk_reward is not None and float(risk_reward) < 1.3:
        return {
            "label": "Blocked by risk",
            "tone": "rose",
            "reason": "Risk reward is below minimum threshold",
            "allowed": False,
            "status": "BLOCKED_RISK",
        }

    return {
        "label": "Eligible",
        "tone": "emerald",
        "reason": trigger.get("reason") or "Signal passes watchlist eligibility checks",
        "allowed": True,
        "status": "ELIGIBLE",
    }


def _watchlist_risk_payload(risk, stale_after_seconds):
    if not risk:
        return None

    validation = validate_trade_plan_direction(
        risk.signal,
        risk.entry_price,
        risk.target1,
    )
    freshness = freshness_status(risk.created_at, stale_after_seconds)
    is_usable = validation["is_valid"] and not freshness["is_stale"]
    reason = _watchlist_risk_reason_text(risk)

    return {
        "symbol": risk.symbol,
        "status": _watchlist_risk_status(freshness, validation),
        "decision": risk.decision,
        "reason": reason,
        "freshness": freshness,
        "is_valid_trade_plan": validation["is_valid"],
        "is_usable": is_usable,
        "validation_errors": validation["errors"],
    }


def _watchlist_computed_risk_payload(payload):
    trigger = payload.get("trigger") or {}
    trade_plan = payload.get("trade_plan") or {}
    selected = _selected_timeframe_record(payload)

    side = trigger.get("side")
    entry = trade_plan.get("entry")
    stop_loss = trade_plan.get("stop_loss")
    target1 = trade_plan.get("target1")
    target2 = trade_plan.get("target2")
    confidence = _timeframe_confidence(selected, payload.get("confirmation"))

    if not side or entry is None or stop_loss is None or target1 is None:
        return None

    try:
        result = _risk_engine.analyze_trade_plan(
            symbol=payload.get("symbol"),
            side=side,
            entry=entry,
            stop_loss=stop_loss,
            target1=target1,
            target2=target2,
            confidence=confidence or 0,
            risk_percent=1,
            fee_bps=DEFAULT_FEE_BPS,
            minimum_reward_target=approval_target_for_policy(
                trade_plan.get("exit_policy"),
                target1,
                target2,
            ),
        )
    except Exception:
        return None

    if not isinstance(result, dict):
        return None

    return {
        "symbol": payload.get("symbol"),
        "decision": result.get("decision"),
        "reason": result.get("reason"),
        "risk_reward": result.get("risk_reward"),
        "position_size": result.get("position_size"),
        "confidence": result.get("confidence"),
        "risk_percent": result.get("risk_percent"),
        "requested_risk_percent": result.get("requested_risk_percent"),
        "position_tier": result.get("position_tier"),
        "is_usable": str(result.get("decision") or "").upper() == "APPROVE",
        "validation_errors": [] if str(result.get("decision") or "").upper() == "APPROVE" else [result.get("reason") or "Computed risk rejected"],
    }


def _selected_timeframe_record(payload):
    trigger = payload.get("trigger") or {}
    setup = payload.get("setup") or {}
    selected_timeframe = (
        trigger.get("entry_timeframe")
        or trigger.get("selected_timeframe")
        or setup.get("entry_timeframe")
        or setup.get("selected_timeframe")
    )
    timeframes = payload.get("timeframes") or []
    selected = _timeframe_record(timeframes, selected_timeframe)
    return selected or (timeframes[0] if timeframes else {})


def _timeframe_record(timeframes, timeframe):
    label = str(timeframe or "").lower()
    return next(
        (
            item
            for item in (timeframes or [])
            if str(item.get("timeframe") or "").lower() == label
        ),
        {},
    )


def _timeframe_confidence(timeframe, confirmation=None):
    confidence = (timeframe or {}).get("confidence")
    if confidence is not None:
        return confidence
    return (confirmation or {}).get("confidence")


def _timeframe_regime(timeframe, confirmation=None):
    regime = (
        (timeframe or {}).get("component_scores", {})
        .get("regime", {})
        .get("value")
    )
    return regime or (timeframe or {}).get("bias") or (confirmation or {}).get("overall_bias")


def _watchlist_risk_status(freshness, validation):
    if freshness.get("is_stale") and not validation.get("is_valid"):
        return "historical_stale_invalid"
    if freshness.get("is_stale"):
        return "historical_stale"
    if validation.get("is_valid"):
        return "current_valid"
    return "current_invalid"


def _watchlist_risk_reason_text(risk):
    for field in ("reason", "message"):
        value = getattr(risk, field, None)
        if value:
            return value

    decision = str(getattr(risk, "decision", "") or "").upper()
    if decision == "APPROVE":
        return "Risk engine approved signal"
    if decision == "REJECT":
        return "Risk engine rejected signal"
    return "Persisted risk decision available"


def _timeframe_value(timeframes, timeframe, key):
    item = timeframes.get(timeframe)

    if not item:
        return None

    return item.get(key)


def _build_signal_diagnostics(db, symbol, timeframe, stale_after_seconds):
    freshness_window = stale_after_seconds_for_timeframe(
        timeframe,
        fallback=stale_after_seconds,
    )
    candle = _latest_candle(db, symbol, timeframe)

    if not candle:
        probability = build_probability_profile(
            db,
            symbol,
            timeframe,
            freshness_window,
        )
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "source": "computed_current",
            "status": "NO_DATA",
            "data_scope": "timeframe",
            "signal": "NO_DATA",
            "bias": "NO_DATA",
            "direction": "UNKNOWN",
            "confidence": 0,
            "score": 0,
            "freshness": freshness_status(None, freshness_window),
            "message": "No latest candle found for symbol/timeframe",
            "contradiction": build_contradiction_report(db, symbol, timeframe, freshness_window),
            "probability": probability,
            **_probability_aliases(probability),
        }

    data = get_ai_inputs(db, symbol, timeframe)
    signal = generate_master_signal(
        data["feature"], data["regime"], data["orderflow"], data["smc"]
    )
    components = score_master_signal_components(
        data["feature"], data["regime"], data["orderflow"], data["smc"]
    )
    probability = build_probability_profile(db, symbol, timeframe, freshness_window)

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "source": "computed_current",
        "status": "OK",
        "data_scope": "timeframe",
        "signal": signal["signal"],
        "bias": signal["bias"],
        "direction": _market_direction(signal["bias"], signal["signal"]),
        "confidence": signal["confidence"],
        "score": signal["score"],
        "current_price": float(candle.close_price),
        "candle_time": candle.candle_time,
        "freshness": freshness_status(
            candle_freshness_timestamp(candle),
            freshness_window,
        ),
        "component_scores": components,
        "reasons": signal["reasons"],
        "contradiction": build_contradiction_report(db, symbol, timeframe, freshness_window),
        "probability": probability,
        **_probability_aliases(probability),
        "inputs": {
            "feature": freshness_status(
                getattr(data["feature"], "CreatedAt", None),
                freshness_window,
            ),
            "regime": freshness_status(
                getattr(data["regime"], "CreatedAt", None),
                freshness_window,
            ),
            "orderflow": freshness_status(
                getattr(data["orderflow"], "CreatedAt", None),
                freshness_window,
            ),
            "smc": freshness_status(
                getattr(data["smc"], "created_at", None),
                freshness_window,
            ),
        },
    }


def _market_direction(bias, signal=None):
    text = f"{bias or ''} {signal or ''}".upper()
    if any(token in text for token in ("LONG", "BULL", "BUY")):
        return "BULLISH"
    if any(token in text for token in ("SHORT", "BEAR", "SELL")):
        return "BEARISH"
    if "NO_DATA" in text:
        return "UNKNOWN"
    return "NEUTRAL"


def _latest_atr(feature, current_price):
    atr = getattr(feature, "ATR", None) if feature else None

    if atr and atr > 0:
        return float(atr)

    return current_price * 0.01


def _latest_persisted_signal(db, symbol, timeframe=None, stale_after_seconds=900):
    candidates = []
    master_signal = MasterSignalRepository().latest(db, symbol, timeframe)

    if master_signal:
        candidates.append(
            _persisted_signal_payload(
                "master_signals",
                master_signal.signal,
                master_signal.confidence,
                master_signal.entry_price,
                master_signal.target_price,
                master_signal.created_at,
                stale_after_seconds,
            )
        )

    ai_signal = AISignalRepository().latest(db, symbol, timeframe)

    if ai_signal:
        candidates.append(
            _persisted_signal_payload(
                "ai_signals",
                ai_signal.direction,
                ai_signal.confidence,
                ai_signal.entry_price,
                ai_signal.target_price,
                ai_signal.created_at,
                stale_after_seconds,
            )
        )

    usable = [candidate for candidate in candidates if candidate["is_usable"]]
    ignored = [candidate for candidate in candidates if not candidate["is_usable"]]

    return {
        "latest_usable": _latest_by_created_at(usable),
        "latest_ignored": _latest_by_created_at(ignored),
    }


def _persisted_signal_payload(
    source,
    signal,
    confidence,
    entry_price,
    target_price,
    created_at,
    stale_after_seconds,
):
    validation = validate_trade_plan_direction(signal, entry_price, target_price)
    freshness = freshness_status(created_at, stale_after_seconds)
    is_fresh = not freshness["is_stale"]
    is_usable = is_fresh and validation["is_valid"]

    return {
        "source": source,
        "signal": signal,
        "confidence": confidence,
        "entry_price": entry_price,
        "target_price": target_price,
        "created_at": created_at,
        "freshness": freshness,
        "status": _persisted_signal_status(is_fresh, validation["is_valid"]),
        "is_valid_trade_plan": validation["is_valid"],
        "is_usable": is_usable,
        "ignored_reasons": _ignored_reasons(freshness, validation),
        "validation_errors": validation["errors"],
    }


def _persisted_signal_status(is_fresh, is_valid):
    if is_fresh and is_valid:
        return "current_valid"

    if not is_fresh and not is_valid:
        return "historical_stale_invalid"

    if not is_fresh:
        return "historical_stale"

    return "current_invalid"


def _ignored_reasons(freshness, validation):
    reasons = []

    if freshness["is_stale"]:
        reasons.append("Persisted signal is stale")

    reasons.extend(validation["errors"])

    return reasons


def _latest_by_created_at(candidates):
    if not candidates:
        return None

    return max(candidates, key=lambda item: item["created_at"])
