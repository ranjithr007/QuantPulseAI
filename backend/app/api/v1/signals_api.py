from fastapi import APIRouter, HTTPException, Query

from app.database.models.market_candles import MarketCandle
from app.database.sqlserver import SessionLocal
from app.intelligence.master_ai_engine import generate_master_signal
from app.intelligence.master_ai_engine import score_master_signal_components
from app.intelligence.multi_timeframe_engine import combine_timeframe_signals
from app.intelligence.trade_setup_engine import build_entry_trigger_decision
from app.intelligence.trade_setup_engine import build_trade_setup_decision
from app.repositories.ai_signal_repository import AISignalRepository
from app.repositories.candle_repository import get_latest_candle
from app.repositories.intelligence_repository import get_ai_inputs
from app.repositories.master_signal_repository import MasterSignalRepository
from app.repositories.symbol_repository import SymbolRepository
from app.repositories.trade_plan_repository import TradePlanRepository
from app.trading.trade_plan_engine import build_trade_plan
from app.utils.freshness import freshness_status
from app.utils.signal_validation import validate_trade_plan_direction


router = APIRouter(prefix="/signals", tags=["Signals"])
SUPPORTED_TIMEFRAMES = {"1m", "5m", "15m", "1h", "4h", "1d"}
DEFAULT_TIMEFRAME_STACK = ["5m", "15m", "1h"]
TIMEFRAME_MODES = {
    "scalp": ["1m", "5m", "15m"],
    "intraday": ["5m", "15m", "1h"],
    "swing": ["15m", "1h", "4h"],
    "position": ["1h", "4h", "1d"],
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
        stack = _resolve_timeframe_stack(mode, lower, middle, higher)
        symbols = SymbolRepository().get_active_symbols(db)
        records = [
            _watchlist_row(
                _build_entry_trigger_payload(db, item.symbol, stack, stale_after_seconds)
            )
            for item in symbols
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
        symbols = SymbolRepository().get_active_symbols(db)
        trade_repo = TradePlanRepository()
        records = []

        for item in symbols:
            payload = _build_entry_trigger_payload(
                db,
                item.symbol,
                stack,
                stale_after_seconds,
            )
            records.append(
                _persist_ready_watchlist_payload(
                    db,
                    trade_repo,
                    payload,
                    normalized_side,
                )
            )

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
            "saved": saved,
            "skipped": skipped,
        }

    finally:
        db.close()


@router.get("/{symbol}/multi-timeframe")
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
        stack = _resolve_timeframe_stack(mode, lower, middle, higher)
        timeframes = [
            _build_signal_diagnostics(db, symbol, timeframe, stale_after_seconds)
            for timeframe in stack
        ]
        confirmation = combine_timeframe_signals(timeframes)

        return {
            "symbol": symbol,
            "source": "multi_timeframe_confirmation",
            "mode": mode,
            "timeframes_used": stack,
            "timeframes": timeframes,
            "confirmation": confirmation,
        }

    finally:
        db.close()


@router.get("/{symbol}/trade-setup")
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
        stack = _resolve_timeframe_stack(mode, lower, middle, higher)
        timeframes = [
            _build_signal_diagnostics(db, symbol, timeframe, stale_after_seconds)
            for timeframe in stack
        ]
        confirmation = combine_timeframe_signals(timeframes)
        setup = build_trade_setup_decision(confirmation, timeframes)
        trade_plan = None
        validation = None

        if setup["status"] == "READY":
            candle = _latest_candle(db, symbol, stack[0])
            data = get_ai_inputs(db, symbol, stack[0])
            current_price = float(candle.close_price)
            atr = _latest_atr(data["feature"], current_price)
            trade_plan = build_trade_plan(setup["side"], current_price, atr)
            validation = validate_trade_plan_direction(
                setup["side"],
                trade_plan["entry"],
                trade_plan["target1"],
            )

        return {
            "symbol": symbol,
            "source": "multi_timeframe_trade_setup",
            "mode": mode,
            "timeframes_used": stack,
            "setup": setup,
            "confirmation": confirmation,
            "trade_plan": trade_plan,
            "trade_plan_validation": validation,
            "timeframes": timeframes,
        }

    finally:
        db.close()


@router.get("/{symbol}/entry-trigger")
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
        stack = _resolve_timeframe_stack(mode, lower, middle, higher)
        payload = _build_entry_trigger_payload(db, symbol, stack, stale_after_seconds)
        payload["mode"] = mode
        payload["timeframes_used"] = stack
        return payload

    finally:
        db.close()


@router.get("/{symbol}/diagnostics")
def get_signal_diagnostics(
    symbol: str,
    timeframe: str = Query(default="5m", enum=["1m", "5m", "15m", "1h", "4h", "1d"]),
    stale_after_seconds: int = Query(default=900, ge=1),
):
    db = SessionLocal()

    try:
        return _build_signal_diagnostics(db, symbol, timeframe, stale_after_seconds)

    finally:
        db.close()


@router.get("/{symbol}")
def get_signal(
    symbol: str,
    timeframe: str = Query(default="5m", enum=["1m", "5m", "15m", "1h", "4h", "1d"]),
    stale_after_seconds: int = Query(default=900, ge=1),
):
    db = SessionLocal()

    try:
        candle = _latest_candle(db, symbol, timeframe)

        if not candle:
            return {
                "symbol": symbol,
                "timeframe": timeframe,
                "source": "computed_current",
                "signal": "NO_DATA",
                "confidence": 0,
                "freshness": freshness_status(None, stale_after_seconds),
                "message": "No latest candle found for symbol/timeframe",
            }

        data = get_ai_inputs(db, symbol, timeframe)
        signal = generate_master_signal(
            data["feature"], data["regime"], data["orderflow"], data["smc"]
        )

        current_price = float(candle.close_price)
        atr = _latest_atr(data["feature"], current_price)
        trade_plan = build_trade_plan(signal["signal"], current_price, atr)

        persisted_signal = _latest_persisted_signal(db, symbol, stale_after_seconds)

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "source": "computed_current",
            "signal": signal["signal"],
            "bias": signal["bias"],
            "confidence": signal["confidence"],
            "score": signal["score"],
            "current_price": current_price,
            "candle_time": candle.candle_time,
            "freshness": freshness_status(candle.candle_time, stale_after_seconds),
            "trade_plan": trade_plan,
            "reasons": signal["reasons"],
            "inputs": {
                "feature": freshness_status(
                    getattr(data["feature"], "CreatedAt", None),
                    stale_after_seconds,
                ),
                "regime": freshness_status(
                    getattr(data["regime"], "CreatedAt", None),
                    stale_after_seconds,
                ),
                "orderflow": freshness_status(
                    getattr(data["orderflow"], "CreatedAt", None),
                    stale_after_seconds,
                ),
                "smc": freshness_status(
                    getattr(data["smc"], "created_at", None),
                    stale_after_seconds,
                ),
            },
            "latest_persisted_signal": persisted_signal["latest_usable"],
            "ignored_persisted_signal": persisted_signal["latest_ignored"],
        }

    finally:
        db.close()


def _latest_candle(db, symbol, timeframe):
    return get_latest_candle(db, symbol, timeframe)


def _resolve_timeframe_stack(mode=None, lower=None, middle=None, higher=None):
    stack = _timeframe_stack_from_mode(mode)
    explicit = [lower, middle, higher]

    for index, timeframe in enumerate(explicit):
        if timeframe:
            stack[index] = timeframe

    for timeframe in stack:
        if timeframe not in SUPPORTED_TIMEFRAMES:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported timeframe: {timeframe}",
            )

    if len(set(stack)) != 3:
        raise HTTPException(
            status_code=400,
            detail="lower, middle, and higher timeframes must be different",
        )

    return stack


def _timeframe_stack_from_mode(mode):
    if mode is None:
        return list(DEFAULT_TIMEFRAME_STACK)

    normalized_mode = mode.lower()

    if normalized_mode not in TIMEFRAME_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported mode: {mode}",
        )

    return list(TIMEFRAME_MODES[normalized_mode])


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
    score = abs(item.get("score_5m") or 0)

    return (
        status_priority,
        failed_count,
        permission_priority,
        side_priority,
        -score,
        item["symbol"],
    )


def _persist_ready_watchlist_payload(db, trade_repo, payload, side_filter=None):
    symbol = payload["symbol"]
    trigger = payload["trigger"]
    side = trigger["side"]
    trade_plan = payload["trade_plan"]
    validation = payload["trade_plan_validation"]
    lower = payload["timeframes"][0] if payload["timeframes"] else {}

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

    if trade_repo.has_open_trade(db, symbol, side):
        return {
            **base,
            "action": "skipped_existing_open",
            "message": "Open trade plan already exists for symbol and side",
        }

    trade = trade_repo.save_ready_trade_plan(
        db,
        symbol,
        side,
        trade_plan,
        lower.get("confidence", 0),
    )

    return {
        **base,
        "action": "saved",
        "trade_plan_id": trade.id,
        "entry_price": trade.entry_price,
        "stop_loss": trade.stop_loss,
        "target1": trade.target1,
        "target2": trade.target2,
        "risk_reward": trade.risk_reward,
        "confidence": trade.confidence,
    }


def _build_entry_trigger_payload(db, symbol, timeframes_to_use, stale_after_seconds):
    timeframes = [
        _build_signal_diagnostics(db, symbol, timeframe, stale_after_seconds)
        for timeframe in timeframes_to_use
    ]
    confirmation = combine_timeframe_signals(timeframes)
    trigger = build_entry_trigger_decision(confirmation, timeframes)
    trade_plan = None
    validation = None

    if trigger["status"] == "READY":
        lower_timeframe = timeframes_to_use[0]
        candle = _latest_candle(db, symbol, lower_timeframe)
        data = get_ai_inputs(db, symbol, lower_timeframe)
        current_price = float(candle.close_price)
        atr = _latest_atr(data["feature"], current_price)
        trade_plan = build_trade_plan(trigger["side"], current_price, atr)
        validation = validate_trade_plan_direction(
            trigger["side"],
            trade_plan["entry"],
            trade_plan["target1"],
        )

    return {
        "symbol": symbol,
        "source": "multi_timeframe_entry_trigger",
        "trigger": trigger,
        "confirmation": confirmation,
        "trade_plan": trade_plan,
        "trade_plan_validation": validation,
        "timeframes": timeframes,
    }


def _watchlist_row(payload):
    timeframes = {
        item["timeframe"]: item
        for item in payload["timeframes"]
    }
    trade_plan = payload["trade_plan"] or {}
    trigger = payload["trigger"]
    confirmation = payload["confirmation"]

    return {
        "symbol": payload["symbol"],
        "status": trigger["status"],
        "side": trigger["side"],
        "overall_bias": confirmation["overall_bias"],
        "trade_permission": confirmation["trade_permission"],
        "reason": trigger["reason"],
        "failed_conditions": [
            item["name"]
            for item in trigger.get("conditions", [])
            if not item["passed"]
        ],
        "bias_5m": _timeframe_value(timeframes, "5m", "bias"),
        "bias_15m": _timeframe_value(timeframes, "15m", "bias"),
        "bias_1h": _timeframe_value(timeframes, "1h", "bias"),
        "score_5m": _timeframe_value(timeframes, "5m", "score"),
        "entry": trade_plan.get("entry"),
        "stop_loss": trade_plan.get("stop_loss"),
        "target1": trade_plan.get("target1"),
        "risk_reward": trade_plan.get("risk_reward"),
        "price_precision": trade_plan.get("price_precision"),
    }


def _timeframe_value(timeframes, timeframe, key):
    item = timeframes.get(timeframe)

    if not item:
        return None

    return item.get(key)


def _build_signal_diagnostics(db, symbol, timeframe, stale_after_seconds):
    candle = _latest_candle(db, symbol, timeframe)

    if not candle:
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "source": "computed_current",
            "signal": "NO_DATA",
            "bias": "NO_DATA",
            "confidence": 0,
            "score": 0,
            "freshness": freshness_status(None, stale_after_seconds),
            "message": "No latest candle found for symbol/timeframe",
        }

    data = get_ai_inputs(db, symbol, timeframe)
    signal = generate_master_signal(
        data["feature"], data["regime"], data["orderflow"], data["smc"]
    )
    components = score_master_signal_components(
        data["feature"], data["regime"], data["orderflow"], data["smc"]
    )

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "source": "computed_current",
        "signal": signal["signal"],
        "bias": signal["bias"],
        "confidence": signal["confidence"],
        "score": signal["score"],
        "current_price": float(candle.close_price),
        "candle_time": candle.candle_time,
        "freshness": freshness_status(candle.candle_time, stale_after_seconds),
        "component_scores": components,
        "reasons": signal["reasons"],
        "inputs": {
            "feature": freshness_status(
                getattr(data["feature"], "CreatedAt", None),
                stale_after_seconds,
            ),
            "regime": freshness_status(
                getattr(data["regime"], "CreatedAt", None),
                stale_after_seconds,
            ),
            "orderflow": freshness_status(
                getattr(data["orderflow"], "CreatedAt", None),
                stale_after_seconds,
            ),
            "smc": freshness_status(
                getattr(data["smc"], "created_at", None),
                stale_after_seconds,
            ),
        },
    }


def _latest_atr(feature, current_price):
    atr = getattr(feature, "ATR", None) if feature else None

    if atr and atr > 0:
        return float(atr)

    return current_price * 0.01


def _latest_persisted_signal(db, symbol, stale_after_seconds=900):
    candidates = []
    master_signal = MasterSignalRepository().latest(db, symbol)

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

    ai_signal = AISignalRepository().latest(db, symbol)

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
