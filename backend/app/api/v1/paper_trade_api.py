import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from math import isfinite

from fastapi import APIRouter, Body, Query
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from app.contracts.bundle import PaperTradeBundleResponse
from app.contracts.control import PaperTradeExecutionResponse

from app.api.v1.derivatives_api import build_derivatives_payload
from app.backtesting.walk_forward_validator import PHASE2_OFFICIAL_TIMEFRAMES
from app.backtesting.walk_forward_validator import PHASE2_VALIDATION_CONTRACT_VERSION
from app.database.models.paper_trade import PaperTrade
from app.database.models.point_in_time_snapshots import DecisionSnapshot
from app.database.models.risk_decision import RiskDecision
from app.database.models.trade_plan import TradePlan
from app.database.sqlserver import SessionLocal
from app.paper_trading.fill_model import build_fill_profile
from app.paper_trading.entry_price_service import get_current_paper_entry_mark
from app.paper_trading.inr_sizing import build_inr_paper_sizing
from app.paper_trading.inr_sizing import build_inr_paper_wallet
from app.paper_trading.inr_sizing import fit_inr_paper_sizing_to_margin_capacity
from app.paper_trading.measurement import MeasurementGates
from app.paper_trading.measurement import attach_regime_outcome_context
from app.paper_trading.measurement import attach_scenario_context
from app.paper_trading.measurement import build_measurement_report
from app.paper_trading.evidence_scope import production_paper_trade_records
from app.paper_trading.reentry_policy import PAPER_STOP_REENTRY_COOLDOWN_MINUTES
from app.paper_trading.reentry_policy import same_side_stop_reentry_cooldown
from app.paper_trading.validation_policy import build_architecture_paper_gate
from app.risk.account_risk import build_account_daily_pnl_snapshot
from app.risk.risk_engine import RiskEngine
from app.risk.confidence_sizing import confidence_sizing_profile
from app.intelligence.contradiction_engine import build_contradiction_report
from app.trading.futures_cost_model import DEFAULT_FEE_BPS
from app.paper_trading.exit_policy import approval_target_for_policy
from app.paper_trading.exit_policy import build_policy_trade_levels
from app.paper_trading.exit_policy import PAPER_ADAPTIVE_EXIT_POLICY
from app.paper_trading.exit_policy import target1_protection_stop
from app.repositories.paper_trade_repository import PaperTradeRepository
from app.repositories.paper_wallet_ledger_repository import PaperWalletLedgerRepository
from app.repositories.automation_settings_repository import DEFAULT_AUTOMATION_SETTINGS
from app.repositories.automation_settings_repository import automation_settings_payload
from app.repositories.automation_settings_repository import get_automation_settings
from app.repositories.automation_settings_repository import PAPER_DAILY_LOSS_LIMIT_CEILING_PERCENT
from app.repositories.automation_settings_repository import PAPER_MAX_OPEN_TRADES
from app.repositories.derivative_repository import DerivativeRepository
from app.repositories.data_quality_event_repository import DataQualityEventRepository
from app.repositories.market_participation_repository import MarketParticipationRepository
from app.repositories.point_in_time_snapshot_repository import list_decision_snapshots
from app.repositories.risk_repository import RiskRepository
from app.repositories.symbol_repository import SymbolRepository
from app.repositories.trade_plan_repository import TradePlanRepository
from app.repositories.strategy_shadow_trade_repository import (
    StrategyShadowTradeRepository,
)
from app.strategies.registry import strategy_definition
from app.strategies.learning import resolve_strategy_definition
from app.strategies.learning import candidate_rearm_blocker
from app.trading.market_participation_guard import market_participation_blockers
from app.utils.freshness import freshness_status
from app.utils.freshness import normalize_timestamp_to_utc
from app.utils.freshness import stale_after_seconds_for_timeframe


router = APIRouter(prefix="/paper-trade", tags=["Paper Trade"])
risk_engine = RiskEngine()
PHASE2_OPPORTUNITY_DECISION_VERSION = "phase2_opportunity_ledger_v1"
PHASE2_RECOVERY_EVENT_SOURCE = "phase2_supervisor"
PHASE2_RECOVERY_EVENT_CATEGORY = "OPPORTUNITY_COVERAGE_RECOVERY"
PHASE2_CHECKPOINT_EVENT_SOURCE = "phase2_daily_checkpoint"
PHASE2_CHECKPOINT_EVENT_CATEGORY = "PHASE2_DAILY_EVIDENCE"
PAPER_RISK_MARK_TIMEFRAME = "5m"
PAPER_RISK_MARK_MAX_AGE_SECONDS = 15 * 60
PAPER_ENTRY_MARK_MAX_AGE_SECONDS = 60
PAPER_ENTRY_MARK_CLOCK_SKEW_SECONDS = 30
_MARKET_PARTICIPATION_UNSET = object()
_CURRENT_SIGNAL_VALIDATION_UNSET = object()
PAPER_STOP_REENTRY_COOLDOWN_REASON = (
    "Same-direction re-entry is cooling down for "
    f"{PAPER_STOP_REENTRY_COOLDOWN_MINUTES} minutes after stop-loss"
)


def build_paper_trade_bundle(db, symbol=None, open_limit=120, closed_limit=200):
    normalized_symbol = symbol.upper() if symbol else None
    repo = PaperTradeRepository()
    official_timeframes = tuple(PHASE2_OFFICIAL_TIMEFRAMES)
    open_trade_rows = repo.list_trades(
        db,
        status="OPEN",
        symbol=normalized_symbol,
        limit=open_limit,
        entry_timeframes=official_timeframes,
    )
    closed_trade_rows = repo.list_trades(
        db,
        status="CLOSED",
        symbol=normalized_symbol,
        limit=closed_limit,
        entry_timeframes=official_timeframes,
    )
    open_trades = [_paper_trade_payload(trade) for trade in open_trade_rows]
    closed_trades = [_paper_trade_payload(trade) for trade in closed_trade_rows]
    performance = repo.performance_summary(
        db,
        symbol=normalized_symbol,
        entry_timeframes=official_timeframes,
    )
    visible_count = repo.count_trades(db, symbol=normalized_symbol)
    auditable_count = repo.count_trades(
        db,
        symbol=normalized_symbol,
        include_quarantined=True,
    )
    account_trades = repo.risk_snapshot_trades(
        db,
        window_start=datetime.utcnow() - timedelta(hours=24),
    )
    account_risk = _account_risk_snapshot(db, account_trades)
    open_trades = _attach_open_trade_price_evidence(open_trades, account_risk)
    paper_wallet = _paper_wallet_snapshot(
        db,
        account_trades,
        account_risk=account_risk,
    )

    return {
        "source": "paper_trade_bundle",
        "symbol_filter": normalized_symbol,
        "marketContext": _market_context_payload(normalized_symbol),
        "accountRisk": account_risk,
        "paperWallet": paper_wallet,
        "ledgerScope": {
            "scope": "PAPER_PRODUCTION",
            "policy": "QA_SYMBOL_QUARANTINE_V1",
            "visible_records": visible_count,
            "quarantined_records": auditable_count - visible_count,
            "auditable_records": auditable_count,
        },
        "performance": {
            **performance,
            "closedTrades": closed_trades,
            "history_records_returned": len(closed_trades),
            "history_is_bounded": performance["closed_trades"] > len(closed_trades),
        },
        "summary": {
            "open": performance["open_trades"],
            "closed": performance["closed_trades"],
            "wins": performance["wins"],
            "losses": performance["losses"],
        },
        "openTrades": {
            "count": performance["open_trades"],
            "records": open_trades,
        },
        "closedTrades": {
            "count": performance["closed_trades"],
            "records": closed_trades,
            "records_returned": len(closed_trades),
            "has_more": performance["closed_trades"] > len(closed_trades),
        },
    }


def _paper_wallet_snapshot(db, trades, account_risk=None):
    account_risk = account_risk or _account_risk_snapshot(db, trades)
    ledger = PaperWalletLedgerRepository().wallet_snapshot(db)
    return build_inr_paper_wallet(
        trades,
        ledger_entries=ledger["recent_entries"],
        ledger_realized_pnl_inr=ledger["realized_pnl_inr"],
        ledger_entry_count=ledger["count"],
        current_prices=account_risk.get("current_prices") or {},
        require_open_prices=True,
    )


def _account_risk_snapshot(db, trades):
    open_trades = [
        trade
        for trade in (trades or [])
        if str(getattr(trade, "status", "") or "").upper() == "OPEN"
    ]
    prices = {}
    price_evidence = {}
    mark_repo = DerivativeRepository()
    open_symbols = {str(trade.symbol).upper() for trade in open_trades}
    try:
        marks_by_symbol = mark_repo.latest_mark_prices(
            db,
            open_symbols,
            timeframe=PAPER_RISK_MARK_TIMEFRAME,
        )
    except SQLAlchemyError:
        db.rollback()
        marks_by_symbol = {}
    for trade in open_trades:
        symbol = str(trade.symbol).upper()
        mark = marks_by_symbol.get(symbol)

        mark_price = _finite_float(getattr(mark, "close_price", None))
        mark_timestamp = getattr(mark, "close_time", None)
        freshness = freshness_status(
            mark_timestamp,
            PAPER_RISK_MARK_MAX_AGE_SECONDS,
        )
        status = "FRESH"
        if mark is None:
            status = "MISSING"
        elif mark_price is None or mark_price <= 0:
            status = "INVALID"
        elif freshness["is_stale"]:
            status = "STALE"
        else:
            prices[symbol] = mark_price
        price_evidence[symbol] = {
            "status": status,
            "timeframe": PAPER_RISK_MARK_TIMEFRAME,
            "price": mark_price,
            "source": getattr(mark, "source", None),
            "as_of": normalize_timestamp_to_utc(mark_timestamp),
            "age_seconds": freshness["data_age_seconds"],
            "stale_after_seconds": PAPER_RISK_MARK_MAX_AGE_SECONDS,
        }

    try:
        auto = automation_settings_payload(get_automation_settings(db))
    except SQLAlchemyError:
        db.rollback()
        auto = DEFAULT_AUTOMATION_SETTINGS

    snapshot = build_account_daily_pnl_snapshot(
        trades,
        prices,
        daily_loss_limit=min(
            float(
                auto.get(
                    "dailyLossLimit",
                    PAPER_DAILY_LOSS_LIMIT_CEILING_PERCENT,
                )
            ),
            PAPER_DAILY_LOSS_LIMIT_CEILING_PERCENT,
        ),
        require_open_prices=True,
    )
    snapshot.update(
        {
            "current_prices": prices,
            "price_evidence": price_evidence,
            "valuation_timeframe": PAPER_RISK_MARK_TIMEFRAME,
            "valuation_complete": snapshot["risk_available"],
            "valued_at": datetime.now(timezone.utc),
        }
    )
    return snapshot


@router.get("/performance")
def get_paper_trade_performance(symbol: str | None = Query(default=None)):
    db = SessionLocal()

    try:
        normalized_symbol = symbol.upper() if symbol else None
        repo = PaperTradeRepository()

        return {
            "source": "paper_trade_performance",
            "symbol_filter": normalized_symbol,
            "performance": repo.performance_summary(
                db,
                symbol=normalized_symbol,
            ),
        }

    except SQLAlchemyError as exc:
        return _paper_trade_unavailable_payload(
            operation="performance",
            symbol_filter=symbol,
            detail="Paper-trade performance is unavailable because the database is not reachable.",
        )

    finally:
        db.close()


@router.get("/measurement")
def get_paper_trade_measurement(
    symbol: str | None = Query(default=None),
    min_closed_trades: int = Query(default=100, ge=1, le=100000),
    min_observation_days: int = Query(default=90, ge=1, le=3650),
    min_profit_factor: float = Query(default=1.3, gt=0, le=100),
    min_expectancy_percent: float = Query(default=0.0, ge=-100, le=100),
    min_total_return_percent: float = Query(default=0.0, ge=-100, le=100000),
    max_drawdown_percent: float = Query(default=20.0, gt=0, le=100),
    min_cohort_closed_trades: int = Query(default=20, ge=1, le=100000),
):
    db = SessionLocal()

    try:
        normalized_symbol = symbol.upper() if symbol else None
        trades = _official_timeframe_records(
            PaperTradeRepository().all_trades(db, symbol=normalized_symbol)
        )
        attach_scenario_context(db, trades)
        attach_regime_outcome_context(db, trades)
        report = build_measurement_report(
            trades,
            gates=MeasurementGates(
                min_closed_trades=min_closed_trades,
                min_observation_days=min_observation_days,
                min_profit_factor=min_profit_factor,
                min_expectancy_percent=min_expectancy_percent,
                min_total_return_percent=min_total_return_percent,
                max_drawdown_percent=max_drawdown_percent,
                min_cohort_closed_trades=min_cohort_closed_trades,
            ),
        )
        report["evidence_scope"] = _phase2_evidence_scope()
        return {
            "source": "extended_paper_trade_measurement",
            "symbol_filter": normalized_symbol,
            "report": report,
            "architecture_gate": build_architecture_paper_gate(report),
        }
    except SQLAlchemyError:
        return _paper_trade_unavailable_payload(
            operation="measurement",
            symbol_filter=symbol,
            detail="Paper-trade measurement is unavailable because the database is not reachable.",
        )
    finally:
        db.close()


@router.get("/opportunities")
def get_phase2_opportunity_accounting(
    symbol: str | None = Query(default=None),
    since_hours: int = Query(default=24, ge=1, le=2160),
    scheduler_grace_minutes: int = Query(default=15, ge=0, le=120),
    limit: int = Query(default=10000, ge=1, le=100000),
):
    db = SessionLocal()

    try:
        normalized_symbol = symbol.upper() if symbol else None
        created_after = datetime.utcnow() - timedelta(hours=since_hours)
        records = list_decision_snapshots(
            db,
            decision_version=PHASE2_OPPORTUNITY_DECISION_VERSION,
            symbol=normalized_symbol,
            created_after=created_after,
            limit=limit,
        )
        expected_symbols = (
            [normalized_symbol]
            if normalized_symbol
            else [
                item.symbol
                for item in SymbolRepository().get_active_symbols(db)
            ]
        )
        return _phase2_opportunity_report(
            records,
            normalized_symbol,
            since_hours,
            limit,
            expected_symbols,
            scheduler_grace_minutes,
        )
    except SQLAlchemyError:
        return {
            "source": "phase2_opportunity_accounting",
            "status": "UNAVAILABLE",
            "symbol_filter": symbol.upper() if symbol else None,
            "detail": "Opportunity accounting is unavailable because the database is not reachable.",
        }
    finally:
        db.close()


@router.get("/lifecycle-funnel")
def get_phase2_lifecycle_funnel(
    symbol: str | None = Query(default=None),
    since_hours: int = Query(default=24, ge=1, le=2160),
    stale_after_seconds: int = Query(default=900, ge=1),
):
    """Expose the live Phase 2 path without manufacturing execution events."""
    db = SessionLocal()
    normalized_symbol = symbol.upper() if symbol else None
    cutoff = datetime.utcnow() - timedelta(hours=since_hours)

    try:
        opportunity_records = list_decision_snapshots(
            db,
            decision_version=PHASE2_OPPORTUNITY_DECISION_VERSION,
            symbol=normalized_symbol,
            created_after=cutoff,
            limit=100000,
        )
        expected_symbols = (
            [normalized_symbol]
            if normalized_symbol
            else [item.symbol for item in SymbolRepository().get_active_symbols(db)]
        )
        opportunity = _phase2_opportunity_report(
            opportunity_records,
            normalized_symbol,
            since_hours,
            100000,
            expected_symbols,
            15,
        )

        plan_query = db.query(TradePlan).filter(TradePlan.created_at >= cutoff)
        trade_query = db.query(PaperTrade).filter(PaperTrade.created_at >= cutoff)
        if normalized_symbol:
            plan_query = plan_query.filter(TradePlan.symbol == normalized_symbol)
            trade_query = trade_query.filter(PaperTrade.symbol == normalized_symbol)

        plans = _official_timeframe_records(plan_query.all())
        open_plans = _phase2_open_trade_plans(plans)
        paper_trades = _official_timeframe_records(trade_query.all())
        _, candidates = build_paper_trade_candidates(
            db,
            normalized_symbol,
            stale_after_seconds,
        )
        approved_candidates = [
            item
            for item in candidates
            if (item.get("risk_decision") or {}).get("decision") == "APPROVE"
        ]
        eligible_candidates = [item for item in candidates if item.get("eligible")]
        executor_ready_candidates = _phase2_executor_ready_candidates(candidates)
        candidate_blocks = _phase2_executor_blockers(candidates)

        open_trades = [item for item in paper_trades if item.status == "OPEN"]
        closed_trades = [item for item in paper_trades if item.status == "CLOSED"]
        status, next_action = _phase2_lifecycle_state(
            opportunity,
            open_plans,
            approved_candidates,
            executor_ready_candidates,
            open_trades,
        )
        return {
            "source": "phase2_paper_trade_lifecycle_funnel",
            "status": status,
            "next_action": next_action,
            "symbol_filter": normalized_symbol,
            "window_hours": since_hours,
            "evidence_scope": _phase2_evidence_scope(),
            "coverage": opportunity.get("coverage"),
            "stages": [
                {"key": "evaluated", "label": "Evaluated", "count": opportunity.get("total_evaluations", 0)},
                {
                    "key": "ready",
                    "label": "Current READY",
                    "count": opportunity.get("actionable_ready_count", 0),
                },
                {"key": "queued", "label": "Queued plans", "count": len(open_plans)},
                {"key": "risk_approved", "label": "Risk approved", "count": len(approved_candidates)},
                {
                    "key": "executor_ready",
                    "label": "Executor ready",
                    "count": len(executor_ready_candidates),
                },
                {"key": "open", "label": "Open trades", "count": len(open_trades)},
                {"key": "closed", "label": "Closed trades", "count": len(closed_trades)},
            ],
            "current": {
                "actionable_ready": opportunity.get("actionable_ready_count", 0),
                "open_plans": len(open_plans),
                "plans_created_24h": len(plans),
                "candidate_count": len(candidates),
                "eligible_candidates": len(eligible_candidates),
                "executor_ready_candidates": len(executor_ready_candidates),
                "open_trades": len(open_trades),
            },
            "blockers": {
                "opportunity": opportunity.get("by_block_reason") or {},
                "executor": dict(candidate_blocks.most_common()),
            },
        }
    except SQLAlchemyError:
        return {
            "source": "phase2_paper_trade_lifecycle_funnel",
            "status": "UNAVAILABLE",
            "next_action": "Restore canonical SQL Server evidence storage.",
            "symbol_filter": normalized_symbol,
            "window_hours": since_hours,
            "stages": [],
        }
    finally:
        db.close()


@router.get("/rolling-validation")
def get_phase2_rolling_validation(
    symbol: str | None = Query(default=None),
):
    db = SessionLocal()
    normalized_symbol = symbol.upper() if symbol else None

    try:
        return {
            "source": "phase2_rolling_paper_validation",
            "status": "OK",
            "symbol_filter": normalized_symbol,
            "evidence_scope": _phase2_evidence_scope(),
            "windows": [
                _build_phase2_rolling_window(db, normalized_symbol, days)
                for days in (7, 30)
            ],
        }
    except SQLAlchemyError:
        return {
            "source": "phase2_rolling_paper_validation",
            "status": "UNAVAILABLE",
            "symbol_filter": normalized_symbol,
            "windows": [],
        }
    finally:
        db.close()


@router.post("/recovery-events")
def record_phase2_recovery_event(payload: dict = Body(...)):
    db = SessionLocal()

    try:
        status = str(payload.get("status") or "UNKNOWN").upper()[:20]
        blocked = status in {"UNRESOLVED", "RETRY_FAILED"}
        severity = "error" if blocked else "info" if status == "RECOVERED" else "warning"
        records = DataQualityEventRepository().record_events(
            db,
            [
                {
                    "symbol": "SYSTEM",
                    "timeframe": "1h",
                    "source": PHASE2_RECOVERY_EVENT_SOURCE,
                    "category": PHASE2_RECOVERY_EVENT_CATEGORY,
                    "severity": severity,
                    "status": status,
                    "blocked": blocked,
                    "reason": payload.get("reason") or "Phase 2 coverage recovery event",
                    "details": {
                        "gap_signature": payload.get("gap_signature"),
                        "missing_before": payload.get("missing_before"),
                        "missing_after": payload.get("missing_after"),
                        "repair_action": payload.get("repair_action"),
                        "error": payload.get("error"),
                    },
                    "observed_at": payload.get("observed_at"),
                    "effective_at": payload.get("effective_at") or payload.get("observed_at"),
                }
            ],
        )
        return {
            "source": "phase2_recovery_history",
            "status": "RECORDED",
            "record": records[0] if records else None,
        }
    finally:
        db.close()


@router.get("/recovery-events")
def get_phase2_recovery_events(
    limit: int = Query(default=50, ge=1, le=500),
):
    db = SessionLocal()

    try:
        records = DataQualityEventRepository().list_events(
            db,
            source=PHASE2_RECOVERY_EVENT_SOURCE,
            category=PHASE2_RECOVERY_EVENT_CATEGORY,
            limit=limit,
        )
        outcomes = Counter(item["status"] for item in records)
        return {
            "source": "phase2_recovery_history",
            "status": "OK",
            "count": len(records),
            "summary": {
                "attempts": outcomes.get("ATTEMPTED", 0),
                "recovered": outcomes.get("RECOVERED", 0),
                "unresolved": outcomes.get("UNRESOLVED", 0),
                "retry_failed": outcomes.get("RETRY_FAILED", 0),
                "by_outcome": dict(outcomes),
            },
            "latest": records[0] if records else None,
            "records": records,
        }
    finally:
        db.close()


@router.post("/evidence-checkpoints")
def create_phase2_evidence_checkpoint(payload: dict = Body(default={})):
    db = SessionLocal()

    try:
        return record_phase2_evidence_checkpoint(
            db,
            checkpoint_date=payload.get("checkpoint_date"),
            observed_at=payload.get("observed_at"),
        )
    finally:
        db.close()


@router.get("/evidence-checkpoints")
def get_phase2_evidence_checkpoints(
    limit: int = Query(default=30, ge=1, le=365),
):
    db = SessionLocal()

    try:
        records = DataQualityEventRepository().list_events(
            db,
            source=PHASE2_CHECKPOINT_EVENT_SOURCE,
            category=PHASE2_CHECKPOINT_EVENT_CATEGORY,
            limit=limit,
        )
        return {
            "source": "phase2_daily_evidence_checkpoint",
            "status": "OK",
            "count": len(records),
            "latest": records[0] if records else None,
            "records": records,
        }
    finally:
        db.close()


@router.get("/bundle", response_model=PaperTradeBundleResponse)
def get_paper_trade_bundle(
    symbol: str | None = Query(default=None),
    include_all: bool = Query(default=False),
):
    db = SessionLocal()

    try:
        return build_paper_trade_bundle(
            db,
            symbol=symbol,
            open_limit=120,
            closed_limit=200,
        )

    except SQLAlchemyError:
        return _paper_trade_unavailable_payload(
            operation="bundle",
            symbol_filter=symbol,
            detail="Paper-trade bundle is unavailable because the database is not reachable.",
        )

    finally:
        db.close()


@router.get("/trades")
def get_paper_trades(
    status: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    page: int = Query(default=1, ge=1),
    official_timeframes_only: bool = Query(default=False),
):
    db = SessionLocal()

    try:
        normalized_status = status.upper() if status else None
        normalized_symbol = symbol.upper() if symbol else None
        repo = PaperTradeRepository()
        entry_timeframes = (
            tuple(PHASE2_OFFICIAL_TIMEFRAMES)
            if official_timeframes_only
            else None
        )
        total_count = repo.count_trades(
            db,
            status=normalized_status,
            symbol=normalized_symbol,
            entry_timeframes=entry_timeframes,
        )
        records = [
            _paper_trade_payload(trade)
            for trade in repo.list_trades(
                db,
                status=normalized_status,
                symbol=normalized_symbol,
                limit=limit,
                offset=(page - 1) * limit,
                entry_timeframes=entry_timeframes,
            )
        ]

        return {
            "source": "paper_trades",
            "status_filter": normalized_status,
            "symbol_filter": normalized_symbol,
            "count": len(records),
            "total_count": total_count,
            "page": page,
            "page_size": limit,
            "total_pages": max(1, (total_count + limit - 1) // limit),
            "has_next": page * limit < total_count,
            "has_previous": page > 1,
            "summary": _summarize_paper_trades(records),
            "records": records,
        }

    except SQLAlchemyError as exc:
        return _paper_trade_unavailable_payload(
            operation="trades",
            symbol_filter=symbol,
            status_filter=normalized_status,
            detail="Paper-trade list is unavailable because the database is not reachable.",
        )

    finally:
        db.close()


@router.get("/candidates")
def get_paper_trade_candidates(
    symbol: str | None = Query(default=None),
    stale_after_seconds: int = Query(default=900, ge=1),
):
    db = SessionLocal()

    try:
        normalized_symbol, records = build_paper_trade_candidates(
            db,
            symbol,
            stale_after_seconds,
        )
        eligible = [
            item
            for item in records
            if item["eligible"]
        ]
        selected = [
            item
            for item in records
            if (item.get("arbitration") or {}).get(
                "selected_for_official_execution"
            )
            is True
        ]

        return {
            "source": "paper_trade_candidates",
            "symbol_filter": normalized_symbol,
            "count": len(records),
            "eligible_count": len(eligible),
            "blocked_count": len(records) - len(eligible),
            "official_selected_count": len(selected),
            "records": records,
        }

    except SQLAlchemyError as exc:
        return _paper_trade_unavailable_payload(
            operation="candidates",
            symbol_filter=symbol,
            detail="Paper-trade candidates are unavailable because the database is not reachable.",
        )

    finally:
        db.close()


@router.get("/fill-model")
def get_paper_trade_fill_model(
    side: str = Query(...),
    planned_entry_price: float = Query(..., gt=0),
    stop_loss: float | None = Query(default=None),
    target1: float | None = Query(default=None),
    confidence: float = Query(default=50, ge=0, le=100),
    risk_reward: float | None = Query(default=None),
    fee_bps: float = Query(default=DEFAULT_FEE_BPS, ge=0, le=1000),
):
    return {
        "source": "paper_trade_fill_model",
        "profile": build_fill_profile(
            side=side,
            planned_entry_price=planned_entry_price,
            stop_loss=stop_loss,
            target1=target1,
            confidence=confidence,
            risk_reward=risk_reward,
            fee_bps=fee_bps,
        ),
    }


@router.post("/execute-candidates", response_model=PaperTradeExecutionResponse)
def execute_paper_trade_candidates(
    symbol: str | None = Query(default=None),
    stale_after_seconds: int = Query(default=900, ge=1),
):
    return execute_paper_trade_candidates_for_symbol(
        symbol=symbol,
        stale_after_seconds=stale_after_seconds,
    )


def execute_paper_trade_candidates_for_symbol(symbol=None, stale_after_seconds=900):
    db = SessionLocal()

    try:
        normalized_symbol, records = build_paper_trade_candidates(
            db,
            symbol,
            stale_after_seconds,
        )
        repo = PaperTradeRepository()
        try:
            auto = automation_settings_payload(get_automation_settings(db))
        except Exception:
            db.rollback()
            auto = DEFAULT_AUTOMATION_SETTINGS
        executed = []
        skipped = []
        shadow_execution = _safe_execute_strategy_shadow_candidates(
            db,
            records,
            auto,
        )

        eligible_by_symbol = defaultdict(list)
        for candidate in records:
            candidate_plan = candidate.get("trade_plan") or {}
            plan_definition = resolve_strategy_definition(
                db,
                candidate_plan.get("strategy_id"),
                candidate_plan.get("strategy_version"),
            ) or {}
            if (
                candidate["eligible"]
                and plan_definition.get("official_execution_enabled") is not True
            ):
                skipped.append(
                    {
                        "symbol": candidate["symbol"],
                        "side": candidate["side"],
                        "action": "skipped_research_only_official_execution",
                        "strategy_id": plan_definition.get("id"),
                        "blocked_reasons": [
                            "Strategy remains in isolated Strategy Paper research; "
                            "official paper execution requires the strategy's "
                            "explicit execution flag"
                        ],
                    }
                )
                continue
            if not candidate["eligible"]:
                coin_blockers = (
                    candidate.get("blocker_scopes", {}).get("coin") or []
                )
                if PAPER_STOP_REENTRY_COOLDOWN_REASON in coin_blockers:
                    action = "skipped_same_side_stop_cooldown"
                elif "Active trade already exists for this coin" in coin_blockers:
                    action = "skipped_existing_open_paper_trade"
                else:
                    action = "skipped_not_eligible"
                skipped.append(
                    {
                        "symbol": candidate["symbol"],
                        "side": candidate["side"],
                        "action": action,
                        "blocked_reasons": candidate["blocked_reasons"],
                        "stop_reentry_cooldown": candidate.get(
                            "stop_reentry_cooldown"
                        ),
                    }
                )
                continue

            automation_blockers = _automation_execution_blockers(auto, candidate)
            if automation_blockers:
                skipped.append(
                    {
                        "symbol": candidate["symbol"],
                        "side": candidate["side"],
                        "action": "skipped_automation_control",
                        "blocked_reasons": automation_blockers,
                        "blocker_scopes": {
                            "trade": [],
                            "coin": [],
                            "account": automation_blockers,
                        },
                    }
                )
                continue
            eligible_by_symbol[str(candidate["symbol"]).upper()].append(candidate)

        for candidate_symbol, candidates in sorted(eligible_by_symbol.items()):
            try:
                repo.acquire_account_execution_lock(db)
            except (RuntimeError, SQLAlchemyError):
                db.rollback()
                skipped.extend(
                    {
                        "symbol": candidate["symbol"],
                        "side": candidate["side"],
                        "action": "skipped_account_reservation_unavailable",
                        "blocked_reasons": [
                            "Atomic account capacity reservation is unavailable"
                        ],
                    }
                    for candidate in candidates
                )
                continue

            if repo.has_open_trade(db, candidate_symbol):
                skipped.extend(
                    {
                        "symbol": candidate["symbol"],
                        "side": candidate["side"],
                        "action": "skipped_existing_open_paper_trade",
                    }
                    for candidate in candidates
                )
                db.rollback()
                continue

            winner = max(
                candidates,
                key=lambda item: _paper_trade_candidate_rank(item, db),
            )
            skipped.extend(
                {
                    "symbol": candidate["symbol"],
                    "side": candidate["side"],
                    "action": "skipped_weaker_symbol_candidate",
                    "selected_trade_plan_id": winner["trade_plan"]["id"],
                    "selected_strategy_id": winner["trade_plan"].get("strategy_id"),
                    "candidate_strategy_id": candidate["trade_plan"].get("strategy_id"),
                }
                for candidate in candidates
                if candidate is not winner
            )

            candidate = winner
            account_trades = repo.risk_snapshot_trades(
                db,
                window_start=datetime.utcnow() - timedelta(hours=24),
            )
            stop_reentry_cooldown = same_side_stop_reentry_cooldown(
                account_trades,
                candidate_symbol,
                candidate["side"],
            )
            if stop_reentry_cooldown["active"]:
                skipped.append(
                    {
                        "symbol": candidate["symbol"],
                        "side": candidate["side"],
                        "action": "skipped_same_side_stop_cooldown",
                        "blocked_reasons": [PAPER_STOP_REENTRY_COOLDOWN_REASON],
                        "stop_reentry_cooldown": stop_reentry_cooldown,
                    }
                )
                db.rollback()
                continue
            locked_account_risk = _account_risk_snapshot(db, account_trades)
            if not locked_account_risk.get("risk_available", False):
                skipped.append(
                    {
                        "symbol": candidate["symbol"],
                        "side": candidate["side"],
                        "action": "skipped_account_risk_unavailable",
                        "blocked_reasons": [
                            "Fresh account-wide mark-price valuation is unavailable"
                        ],
                        "account_risk": locked_account_risk,
                    }
                )
                db.rollback()
                continue
            if (
                auto.get("dailyLossLimitEnabled", False)
                and locked_account_risk.get("limit_reached")
            ):
                skipped.append(
                    {
                        "symbol": candidate["symbol"],
                        "side": candidate["side"],
                        "action": "skipped_account_daily_loss_limit",
                        "blocked_reasons": [
                            "Account-wide daily loss limit reached"
                        ],
                        "account_risk": locked_account_risk,
                    }
                )
                db.rollback()
                continue
            wallet = _paper_wallet_snapshot(
                db,
                account_trades,
                account_risk=locked_account_risk,
            )
            remaining_margin_capacity = float(
                wallet["remaining_margin_capacity_inr"]
            )
            if remaining_margin_capacity > 0:
                candidate["paper_sizing"] = (
                    fit_inr_paper_sizing_to_margin_capacity(
                        candidate.get("paper_sizing") or {},
                        remaining_margin_capacity,
                    )
                )
            candidate_margin = float(
                (candidate.get("paper_sizing") or {}).get("margin_used_inr") or 0
            )
            effective_max_open_trades = min(
                int(auto.get("maxOpenTrades", PAPER_MAX_OPEN_TRADES)),
                PAPER_MAX_OPEN_TRADES,
            )
            if (
                auto.get("maxOpenTradesEnabled", False)
                and wallet["open_position_count"] >= effective_max_open_trades
            ):
                skipped.append(
                    {
                        "symbol": candidate["symbol"],
                        "side": candidate["side"],
                        "action": "skipped_account_open_trade_cap",
                    }
                )
                db.rollback()
                continue
            if candidate_margin > remaining_margin_capacity:
                skipped.append(
                    {
                        "symbol": candidate["symbol"],
                        "side": candidate["side"],
                        "action": "skipped_inr_margin_cap",
                        "required_margin_inr": candidate_margin,
                        "remaining_margin_capacity_inr": wallet[
                            "remaining_margin_capacity_inr"
                        ],
                    }
                )
                db.rollback()
                continue
            trade_plan_id = candidate["trade_plan"]["id"]
            if repo.has_trade_for_plan(db, trade_plan_id):
                skipped.append(
                    {
                        "symbol": candidate["symbol"],
                        "side": candidate["side"],
                        "action": "skipped_existing_paper_trade_for_plan",
                        "trade_plan_id": trade_plan_id,
                    }
                )
                db.rollback()
                continue

            live_mark = _current_paper_entry_mark(candidate_symbol)
            candidate, reprice_error = _rebase_paper_trade_candidate(
                candidate,
                live_mark,
            )
            if reprice_error:
                skipped.append(
                    {
                        "symbol": candidate_symbol,
                        "side": winner["side"],
                        "action": "skipped_execution_price_unavailable",
                        "blocked_reasons": [reprice_error],
                    }
                )
                db.rollback()
                continue
            candidate["paper_sizing"] = fit_inr_paper_sizing_to_margin_capacity(
                candidate.get("paper_sizing") or {},
                remaining_margin_capacity,
            )

            try:
                paper_trade = repo.save_candidate(db, candidate)
            except IntegrityError:
                db.rollback()
                skipped.append(
                    {
                        "symbol": candidate["symbol"],
                        "side": candidate["side"],
                        "action": "skipped_concurrent_open_paper_trade",
                    }
                )
                continue
            executed.append(
                _paper_trade_payload(
                    paper_trade,
                    fill_profile=candidate.get("fill_profile"),
                )
            )

        return {
            "source": "paper_trade_execution_simulator",
            "symbol_filter": normalized_symbol,
            "candidate_count": len(records),
            "executed_count": len(executed),
            "skipped_count": len(skipped),
            "executed": executed,
            "skipped": skipped,
            "shadow_execution": shadow_execution,
            "strategy_paper_execution": shadow_execution,
        }

    except SQLAlchemyError as exc:
        return _paper_trade_execution_unavailable_payload(
            symbol_filter=symbol,
            detail="Paper-trade execution is unavailable because the database is not reachable.",
        )

    finally:
        db.close()


def _current_paper_entry_mark(symbol):
    """Fetch a direct mark used only at the final paper-entry boundary."""

    return get_current_paper_entry_mark(symbol)


def _rebase_paper_trade_candidate(candidate, live_mark):
    """Reprice a new paper position and all exits from one fresh mark.

    The signal plan remains the authorization record.  Execution risk is
    recalculated independently so a newly opened position can never inherit a
    completed position's entry, stop, or targets.
    """

    mark_price = _finite_float((live_mark or {}).get("mark_price"))
    observed_at = (live_mark or {}).get("observed_at")
    if mark_price is None or mark_price <= 0 or observed_at is None:
        return candidate, "Fresh execution mark price is unavailable"

    try:
        observed_utc = normalize_timestamp_to_utc(observed_at)
        age_seconds = (datetime.now(timezone.utc) - observed_utc).total_seconds()
    except (AttributeError, TypeError, ValueError):
        return candidate, "Execution mark timestamp is invalid"

    if (
        age_seconds > PAPER_ENTRY_MARK_MAX_AGE_SECONDS
        or age_seconds < -PAPER_ENTRY_MARK_CLOCK_SKEW_SECONDS
    ):
        return candidate, "Execution mark price is stale"

    trade_plan = candidate.get("trade_plan") or {}
    authorization_risk = candidate.get("risk_decision") or {}
    side = str(candidate.get("side") or "").upper()
    symbol = str(candidate.get("symbol") or "").upper()
    timeframe = trade_plan.get("entry_timeframe")
    confidence = (
        authorization_risk.get("confidence")
        if authorization_risk.get("confidence") is not None
        else trade_plan.get("confidence") or 0
    )
    fee_bps = float(
        (candidate.get("fill_profile") or {}).get("fee_bps", DEFAULT_FEE_BPS)
    )
    precision = _paper_trade_price_precision(mark_price)
    adaptive_policy = (
        str(trade_plan.get("exit_policy") or "").upper()
        == PAPER_ADAPTIVE_EXIT_POLICY
    )
    signal_entry = _finite_float(trade_plan.get("entry_price"))
    signal_stop = _finite_float(trade_plan.get("stop_loss"))
    planned_stop_percent = (
        abs(signal_entry - signal_stop) / signal_entry * 100
        if adaptive_policy
        and signal_entry is not None
        and signal_entry > 0
        and signal_stop is not None
        else None
    )
    mark_levels = build_policy_trade_levels(
        side,
        mark_price,
        symbol=symbol,
        timeframe=timeframe,
        confidence=confidence,
        fee_bps=fee_bps,
        price_precision=precision,
        execution_profile=(
            PAPER_ADAPTIVE_EXIT_POLICY if adaptive_policy else None
        ),
        stop_loss_percent=planned_stop_percent,
    )
    if mark_levels is None:
        return candidate, "No paper exit policy is available for the selected timeframe"

    fill_profile = build_fill_profile(
        side=side,
        planned_entry_price=mark_price,
        stop_loss=mark_levels["stop_loss"],
        target1=mark_levels["target2"],
        confidence=confidence,
        risk_reward=mark_levels["target2_net_risk_reward"],
        fee_bps=fee_bps,
    )
    entry_fill = _finite_float(fill_profile.get("entry_fill_price"))
    if entry_fill is None or entry_fill <= 0:
        return candidate, "Paper entry fill could not be calculated from the live mark"

    execution_levels = build_policy_trade_levels(
        side,
        entry_fill,
        symbol=symbol,
        timeframe=timeframe,
        confidence=confidence,
        fee_bps=fee_bps,
        price_precision=_paper_trade_price_precision(entry_fill),
        execution_profile=(
            PAPER_ADAPTIVE_EXIT_POLICY if adaptive_policy else None
        ),
        stop_loss_percent=planned_stop_percent,
    )
    if execution_levels is None:
        return candidate, "Paper exit levels could not be recalculated from the new entry"

    execution_risk = risk_engine.analyze_trade_plan(
        symbol=symbol,
        side=side,
        entry=entry_fill,
        stop_loss=execution_levels["stop_loss"],
        target1=execution_levels["target1"],
        target2=execution_levels["target2"],
        minimum_reward_target=execution_levels["target2"],
        confidence=confidence,
        risk_percent=authorization_risk.get("risk_percent") or 1,
        fee_bps=fee_bps,
    )
    if execution_risk.get("decision") != "APPROVE":
        return candidate, (
            "Repriced paper entry failed risk checks: "
            f"{execution_risk.get('reason') or 'unknown reason'}"
        )

    entry_drift_percent = None
    if signal_entry is not None and signal_entry > 0:
        entry_drift_percent = round((mark_price - signal_entry) / signal_entry * 100, 4)
    fill_profile.update(
        {
            "execution_reference": "FRESH_MARK_PRICE",
            "execution_mark_price": round(mark_price, precision),
            "execution_mark_observed_at": observed_utc.isoformat(),
            "execution_mark_source": live_mark.get("source"),
            "signal_planned_entry_price": signal_entry,
            "entry_drift_percent": entry_drift_percent,
            "effective_risk_reward": execution_risk["risk_reward"],
        }
    )
    execution_risk = {
        **execution_risk,
        "entry_price": execution_risk["entry"],
        "target1": execution_risk["targets"]["t1"],
        "target2": execution_risk["targets"]["t2"],
        "authorization_risk_decision_id": authorization_risk.get("id"),
    }
    execution_stop_percent = (
        abs(entry_fill - float(execution_levels["stop_loss"]))
        / entry_fill
        * 100
    )
    paper_sizing = build_inr_paper_sizing(
        confidence,
        fee_bps=fee_bps,
        stop_loss_percent=execution_stop_percent,
    )

    return {
        **candidate,
        "fill_profile": fill_profile,
        "execution_risk": execution_risk,
        "paper_sizing": paper_sizing,
    }, None


def _attach_open_trade_price_evidence(open_trades, account_risk):
    """Use the same futures mark evidence for PnL display and risk evaluation."""

    current_prices = (account_risk or {}).get("current_prices") or {}
    price_evidence = (account_risk or {}).get("price_evidence") or {}
    records = []
    for trade in open_trades or []:
        symbol = str(trade.get("symbol") or "").upper()
        evidence = price_evidence.get(symbol) or {}
        records.append(
            {
                **trade,
                "current_price": current_prices.get(symbol),
                "current_price_evidence": evidence,
            }
        )
    return records


def _automation_execution_blockers(auto, candidate):
    """Enforce operator controls at the final paper-fill boundary.

    Upstream risk and UI checks are informative only.  This boundary must
    independently fail closed because scheduled jobs call it without the UI.
    """

    if not isinstance(auto, dict):
        return ["Automation settings are unavailable"]

    reasons = []
    if bool(auto.get("emergencyStop")):
        reasons.append("Automation emergency stop is active")
    if not bool(auto.get("enabled")):
        reasons.append("Paper-trade automation is disabled")
    if bool(auto.get("locked", True)):
        reasons.append("Paper-trade automation is locked")
    if str(auto.get("executionMode") or "").upper() != "PAPER":
        reasons.append("Automation execution mode is not PAPER")
    if bool(auto.get("liveExecutionEnabled")):
        reasons.append("Live execution must remain disabled for paper trading")

    symbol = str((candidate or {}).get("symbol") or "").upper()
    allowed_symbols = {
        str(item).strip().upper()
        for item in (auto.get("allowedSymbols") or [])
        if str(item).strip()
    }
    if not symbol or symbol not in allowed_symbols:
        reasons.append(f"{symbol or 'Candidate symbol'} is not in the automation allowlist")

    side = str((candidate or {}).get("side") or "").upper()
    allowed_direction = str(auto.get("direction") or "").upper()
    if allowed_direction not in {"LONG", "SHORT", "BOTH"}:
        reasons.append("Automation direction setting is invalid")
    elif side not in {"LONG", "SHORT"}:
        reasons.append("Candidate direction is invalid")
    elif allowed_direction != "BOTH" and side != allowed_direction:
        reasons.append(f"{side} entries are disabled by the automation direction setting")

    risk = (candidate or {}).get("risk_decision") or {}
    sizing = (candidate or {}).get("paper_sizing") or {}
    _append_automation_numeric_limit_blocker(
        reasons,
        value=risk.get("confidence"),
        limit=auto.get("minConfidence"),
        comparison="minimum",
        missing_reason="Candidate confidence is unavailable",
        blocked_reason="Candidate confidence is below the automation minimum",
    )
    if auto.get("maxRiskPerTradeEnabled", False):
        _append_automation_numeric_limit_blocker(
            reasons,
            value=risk.get("risk_percent"),
            limit=auto.get("maxRiskPerTrade"),
            comparison="maximum",
            missing_reason="Candidate risk percentage is unavailable",
            blocked_reason="Candidate risk percentage exceeds the automation maximum",
        )
    _append_automation_numeric_limit_blocker(
        reasons,
        value=sizing.get("leverage"),
        limit=auto.get("maxLeverage"),
        comparison="maximum",
        missing_reason="Candidate leverage is unavailable",
        blocked_reason="Candidate leverage exceeds the automation maximum",
    )
    _append_automation_numeric_limit_blocker(
        reasons,
        value=sizing.get("position_notional_inr"),
        limit=auto.get("maxPositionSize"),
        comparison="maximum",
        missing_reason="Candidate INR position size is unavailable",
        blocked_reason="Candidate INR position size exceeds the automation maximum",
    )
    return reasons


def _append_automation_numeric_limit_blocker(
    reasons,
    *,
    value,
    limit,
    comparison,
    missing_reason,
    blocked_reason,
):
    try:
        numeric_value = float(value)
        numeric_limit = float(limit)
    except (TypeError, ValueError):
        reasons.append(missing_reason)
        return

    if not isfinite(numeric_value) or not isfinite(numeric_limit):
        reasons.append(missing_reason)
        return

    if comparison == "minimum" and numeric_value < numeric_limit:
        reasons.append(blocked_reason)
    elif comparison == "maximum" and numeric_value > numeric_limit:
        reasons.append(blocked_reason)


QP_TI_001_TIMEFRAME_PRIORITY = {"1h": 1, "2h": 2, "4h": 3, "1d": 4}


def _paper_trade_candidate_rank(candidate, db=None):
    """Deterministically rank eligible candidates for one symbol.

    Validated risk confidence is authoritative, followed by plan confidence,
    strategy priority, reward/risk, higher-timeframe durability, recency, and
    plan id.
    """
    risk = candidate.get("risk_decision") or {}
    plan = candidate.get("trade_plan") or {}
    definition = resolve_strategy_definition(
        db,
        plan.get("strategy_id"),
        plan.get("strategy_version"),
    ) or {}
    created_at = plan.get("created_at")
    created_rank = created_at.timestamp() if hasattr(created_at, "timestamp") else 0.0
    return (
        float(risk.get("confidence") or 0),
        float(plan.get("confidence") or 0),
        int(definition.get("execution_priority") or 0),
        float(plan.get("risk_reward") or 0),
        QP_TI_001_TIMEFRAME_PRIORITY.get(str(plan.get("entry_timeframe") or "").lower(), 0),
        created_rank,
        int(plan.get("id") or 0),
    )


def _annotate_candidate_arbitration(records, auto, db=None):
    """Expose the same per-symbol winner that official execution will use.

    Several strategies may independently produce valid plans for one coin, but
    the official paper book must still open at most one position for that coin.
    Keeping this arbitration result in the API payload prevents clients from
    accidentally treating the first database row as the selected strategy.
    """

    competitors_by_symbol = defaultdict(list)
    executor_blockers_by_id = {}
    for candidate in records:
        plan = candidate.get("trade_plan") or {}
        definition = resolve_strategy_definition(
            db,
            plan.get("strategy_id"),
            plan.get("strategy_version"),
        ) or {}
        blockers = []
        if candidate.get("eligible") is not True:
            blockers.extend(candidate.get("blocked_reasons") or [])
        if definition.get("official_execution_enabled") is not True:
            blockers.append("Strategy is not enabled for official paper execution")
        blockers.extend(_automation_execution_blockers(auto, candidate))
        executor_blockers_by_id[id(candidate)] = list(dict.fromkeys(blockers))
        if not blockers:
            competitors_by_symbol[str(candidate.get("symbol") or "").upper()].append(
                candidate
            )

    ranked_by_symbol = {
        symbol: sorted(
            candidates,
            key=lambda item: _paper_trade_candidate_rank(item, db),
            reverse=True,
        )
        for symbol, candidates in competitors_by_symbol.items()
    }
    annotated = []
    for candidate in records:
        symbol = str(candidate.get("symbol") or "").upper()
        ranked = ranked_by_symbol.get(symbol, [])
        selected = bool(ranked) and candidate is ranked[0]
        rank = next(
            (index for index, item in enumerate(ranked, start=1) if item is candidate),
            None,
        )
        blockers = executor_blockers_by_id[id(candidate)]
        if selected:
            status = "SELECTED"
        elif rank is not None:
            status = "COMPETING"
        else:
            status = "BLOCKED"
        annotated.append(
            {
                **candidate,
                "arbitration": {
                    "status": status,
                    "selected_for_official_execution": selected,
                    "rank": rank,
                    "eligible_competitor_count": len(ranked),
                    "selected_trade_plan_id": (
                        (ranked[0].get("trade_plan") or {}).get("id")
                        if ranked
                        else None
                    ),
                    "selected_strategy_id": (
                        (ranked[0].get("trade_plan") or {}).get("strategy_id")
                        if ranked
                        else None
                    ),
                    "executor_blockers": blockers,
                },
            }
        )
    return annotated


def build_paper_trade_candidates(
    db,
    symbol=None,
    stale_after_seconds=900,
    trades=None,
):
    trade_repo = TradePlanRepository()
    risk_repo = RiskRepository()
    trades = _official_timeframe_records(
        trades if trades is not None else trade_repo.get_open_trades(db)
    )

    if symbol:
        normalized_symbol = symbol.upper()
        trades = [
            trade
            for trade in trades
            if trade.symbol == normalized_symbol
        ]
    else:
        normalized_symbol = None

    latest_risks = risk_repo.latest_for_symbols(
        db,
        [trade.symbol for trade in trades],
    )
    return _finish_paper_trade_candidates(
        db,
        trades,
        risk_repo,
        latest_risks,
        normalized_symbol,
        stale_after_seconds,
    )


def _execute_strategy_shadow_candidates(db, records, auto):
    """Fill every trade-valid strategy in its isolated Strategy Paper book."""
    executed = []
    skipped = []
    if not hasattr(db, "get_bind") or not hasattr(db, "query"):
        return {
            "source": "strategy_shadow_execution_v1",
            "execution_book": "STRATEGY_PAPER",
            "status": "UNAVAILABLE",
            "candidate_count": len(records),
            "executed_count": 0,
            "skipped_count": len(records),
            "executed": [],
            "skipped": [],
        }
    repo = StrategyShadowTradeRepository()
    shadow_history = repo.risk_snapshot_trades(
        db,
        window_start=datetime.utcnow() - timedelta(hours=24),
    )
    strategy_keys = {
        (
            (candidate.get("trade_plan") or {}).get("strategy_id"),
            (candidate.get("trade_plan") or {}).get("strategy_version"),
        )
        for candidate in records
    }
    realized_pnl_by_strategy = repo.realized_pnl_by_strategy(db, strategy_keys)
    live_marks = {}

    for candidate in records:
        plan = candidate.get("trade_plan") or {}
        strategy_id = plan.get("strategy_id")
        strategy_version = plan.get("strategy_version")
        trade_blockers = list(
            (candidate.get("blocker_scopes") or {}).get("trade") or []
        )
        automation_blockers = _automation_execution_blockers(auto, candidate)
        if trade_blockers or automation_blockers:
            skipped.append(
                {
                    "symbol": candidate.get("symbol"),
                    "strategy_id": strategy_id,
                    "action": "skipped_shadow_not_eligible",
                    "blocked_reasons": trade_blockers + automation_blockers,
                }
            )
            continue
        if not strategy_definition(strategy_id):
            skipped.append(
                {
                    "symbol": candidate.get("symbol"),
                    "strategy_id": strategy_id,
                    "action": "skipped_shadow_strategy_unregistered",
                }
            )
            continue
        if repo.has_open_trade(
            db,
            strategy_id,
            strategy_version,
            candidate["symbol"],
        ):
            skipped.append(
                {
                    "symbol": candidate["symbol"],
                    "strategy_id": strategy_id,
                    "action": "skipped_existing_open_shadow_trade",
                }
            )
            continue
        if repo.has_trade_for_plan(db, plan.get("id")):
            skipped.append(
                {
                    "symbol": candidate["symbol"],
                    "strategy_id": strategy_id,
                    "action": "skipped_existing_shadow_trade_for_plan",
                }
            )
            continue
        strategy_history = [
            item
            for item in shadow_history
            if item.strategy_id == strategy_id
            and item.strategy_version == strategy_version
        ]
        cooldown = same_side_stop_reentry_cooldown(
            strategy_history,
            candidate["symbol"],
            candidate["side"],
        )
        if cooldown.get("active"):
            skipped.append(
                {
                    "symbol": candidate["symbol"],
                    "strategy_id": strategy_id,
                    "action": "skipped_shadow_same_side_stop_cooldown",
                    "blocked_reasons": [PAPER_STOP_REENTRY_COOLDOWN_REASON],
                }
            )
            continue
        definition = resolve_strategy_definition(db, strategy_id, strategy_version)
        rearm_blocker = candidate_rearm_blocker(
            db,
            definition or {},
            strategy_history,
            candidate,
        )
        if rearm_blocker:
            skipped.append(
                {
                    "symbol": candidate["symbol"],
                    "strategy_id": strategy_id,
                    "action": "skipped_shadow_signal_not_rearmed",
                    "blocked_reasons": [rearm_blocker],
                }
            )
            continue

        strategy_account_risk = _account_risk_snapshot(db, strategy_history)
        if not strategy_account_risk.get("risk_available", False):
            skipped.append(
                {
                    "symbol": candidate["symbol"],
                    "strategy_id": strategy_id,
                    "action": "skipped_strategy_paper_valuation_unavailable",
                    "blocked_reasons": [
                        "Fresh Strategy Paper mark-price valuation is unavailable"
                    ],
                }
            )
            continue
        if (
            auto.get("dailyLossLimitEnabled", False)
            and strategy_account_risk.get("limit_reached")
        ):
            skipped.append(
                {
                    "symbol": candidate["symbol"],
                    "strategy_id": strategy_id,
                    "action": "skipped_strategy_paper_daily_loss_limit",
                    "blocked_reasons": [
                        "Strategy Paper daily loss limit reached"
                    ],
                }
            )
            continue
        strategy_wallet = build_inr_paper_wallet(
            strategy_history,
            trade_realized_pnl_inr=realized_pnl_by_strategy.get(
                (strategy_id, strategy_version),
                0.0,
            ),
            current_prices=strategy_account_risk.get("current_prices") or {},
            require_open_prices=True,
        )
        sizing = candidate.get("paper_sizing") or build_inr_paper_sizing(
            (candidate.get("execution_risk") or {}).get("confidence")
            or plan.get("confidence")
            or 0
        )
        remaining_strategy_margin = float(
            strategy_wallet["remaining_margin_capacity_inr"]
        )
        if remaining_strategy_margin > 0:
            sizing = fit_inr_paper_sizing_to_margin_capacity(
                sizing,
                remaining_strategy_margin,
            )
            candidate["paper_sizing"] = sizing
        candidate_margin = float(sizing.get("margin_used_inr") or 0)
        effective_max_open_trades = min(
            int(auto.get("maxOpenTrades", PAPER_MAX_OPEN_TRADES)),
            PAPER_MAX_OPEN_TRADES,
        )
        if (
            auto.get("maxOpenTradesEnabled", False)
            and strategy_wallet["open_position_count"] >= effective_max_open_trades
        ):
            skipped.append(
                {
                    "symbol": candidate["symbol"],
                    "strategy_id": strategy_id,
                    "action": "skipped_strategy_paper_open_trade_cap",
                }
            )
            continue
        if candidate_margin > remaining_strategy_margin:
            skipped.append(
                {
                    "symbol": candidate["symbol"],
                    "strategy_id": strategy_id,
                    "action": "skipped_strategy_paper_margin_cap",
                    "required_margin_inr": candidate_margin,
                    "remaining_margin_capacity_inr": strategy_wallet[
                        "remaining_margin_capacity_inr"
                    ],
                }
            )
            continue

        symbol = str(candidate["symbol"]).upper()
        if symbol not in live_marks:
            live_marks[symbol] = _current_paper_entry_mark(symbol)
        repriced, error = _rebase_paper_trade_candidate(
            candidate,
            live_marks[symbol],
        )
        if error:
            skipped.append(
                {
                    "symbol": symbol,
                    "strategy_id": strategy_id,
                    "action": "skipped_shadow_execution_price_unavailable",
                    "blocked_reasons": [error],
                }
            )
            continue
        repriced["paper_sizing"] = fit_inr_paper_sizing_to_margin_capacity(
            repriced.get("paper_sizing") or {},
            remaining_strategy_margin,
        )
        try:
            trade = repo.save_candidate(db, repriced)
        except IntegrityError:
            db.rollback()
            skipped.append(
                {
                    "symbol": symbol,
                    "strategy_id": strategy_id,
                    "action": "skipped_concurrent_open_shadow_trade",
                }
            )
            continue
        executed.append(_strategy_shadow_trade_payload(trade))
        shadow_history.append(trade)

    return {
        "source": "strategy_shadow_execution_v1",
        "execution_book": "STRATEGY_PAPER",
        "candidate_count": len(records),
        "executed_count": len(executed),
        "skipped_count": len(skipped),
        "executed": executed,
        "skipped": skipped,
    }


def _safe_execute_strategy_shadow_candidates(db, records, auto):
    """Keep Strategy Paper failures outside the consolidated execution boundary.

    Strategy Paper books are isolated forward-test evidence. A missing
    migration, transient database error, or malformed strategy-paper record
    must be reported, but it must never prevent an otherwise eligible official
    paper candidate from reaching the shared one-position-per-coin executor.
    """
    try:
        return _execute_strategy_shadow_candidates(db, records, auto)
    except Exception as exc:
        db.rollback()
        return {
            "source": "strategy_shadow_execution_v1",
            "execution_book": "STRATEGY_PAPER",
            "status": "DEGRADED",
            "candidate_count": len(records),
            "executed_count": 0,
            "skipped_count": len(records),
            "executed": [],
            "skipped": [
                {
                    "action": "skipped_shadow_execution_unavailable",
                    "blocked_reasons": [
                        "Strategy Paper execution is temporarily unavailable"
                    ],
                }
            ],
            "error_category": type(exc).__name__,
        }


def _strategy_shadow_trade_payload(trade):
    return {
        "id": trade.id,
        "trade_plan_id": trade.trade_plan_id,
        "symbol": trade.symbol,
        "side": trade.side,
        "strategy_id": trade.strategy_id,
        "strategy_version": trade.strategy_version,
        "strategy_decision_snapshot_id": trade.strategy_decision_snapshot_id,
        "entry_timeframe": trade.entry_timeframe,
        "entry_price": trade.entry_price,
        "stop_loss": trade.stop_loss,
        "target1": trade.target1,
        "target2": trade.target2,
        "status": trade.status,
        "opened_at": trade.opened_at,
    }


def _finish_paper_trade_candidates(
    db,
    trades,
    risk_repo,
    latest_risks,
    normalized_symbol,
    stale_after_seconds,
):
    latest_risks_by_plan = risk_repo.latest_for_trade_plans(
        db,
        [getattr(trade, "id", None) for trade in trades],
    )
    derivative_payloads = {
        trade_symbol: _safe_derivatives_payload(
            db,
            trade_symbol,
            stale_after_seconds=stale_after_seconds,
        )
        for trade_symbol in {trade.symbol for trade in trades}
    }
    market_participation_payloads = MarketParticipationRepository().latest_for_symbols(
        db,
        [trade.symbol for trade in trades],
    )
    strategy_snapshot_ids = {
        trade.strategy_decision_snapshot_id
        for trade in trades
        if getattr(trade, "strategy_decision_snapshot_id", None) is not None
    }
    strategy_snapshots = {
        row.id: row
        for row in (
            db.query(DecisionSnapshot)
            .filter(DecisionSnapshot.id.in_(strategy_snapshot_ids))
            .all()
            if strategy_snapshot_ids
            else []
        )
    }
    current_signal_validations = {
        (trade_symbol, timeframe): _current_signal_validation(
            db,
            trade_symbol,
            timeframe,
            stale_after_seconds,
        )
        for trade_symbol, timeframe in _required_current_signal_keys(trades)
    }
    account_trades = PaperTradeRepository().risk_snapshot_trades(
        db,
        window_start=datetime.utcnow() - timedelta(hours=24),
    )
    account_risk = _account_risk_snapshot(db, account_trades)
    paper_wallet = _paper_wallet_snapshot(
        db,
        account_trades,
        account_risk=account_risk,
    )
    try:
        auto = automation_settings_payload(get_automation_settings(db))
    except SQLAlchemyError:
        db.rollback()
        auto = DEFAULT_AUTOMATION_SETTINGS
    open_symbols = {
        str(item.symbol).upper()
        for item in account_trades
        if str(item.status or "").upper() == "OPEN"
    }
    records = [
        _paper_trade_candidate(
            trade,
            _strategy_plan_risk(
                trade,
                latest_risks_by_plan,
                latest_risks,
            ),
            stale_after_seconds,
            derivative_payloads.get(trade.symbol),
            market_participation=_strategy_market_participation_input(
                trade,
                market_participation_payloads.get(trade.symbol),
            ),
            current_signal_validation=_strategy_core_signal_input(
                trade,
                current_signal_validations.get(
                    (
                        trade.symbol,
                        str(
                            getattr(trade, "entry_timeframe", None) or "1h"
                        ).lower(),
                    )
                ),
            ),
            strategy_snapshot=strategy_snapshots.get(
                getattr(trade, "strategy_decision_snapshot_id", None)
            ),
            strategy_definition_override=resolve_strategy_definition(
                db,
                getattr(trade, "strategy_id", None),
                getattr(trade, "strategy_version", None),
            ),
            account_risk=account_risk,
            paper_wallet=paper_wallet,
            max_open_trades=min(
                int(auto.get("maxOpenTrades", PAPER_MAX_OPEN_TRADES)),
                PAPER_MAX_OPEN_TRADES,
            ),
            max_open_trades_enabled=auto.get("maxOpenTradesEnabled", False),
            daily_loss_limit_enabled=auto.get("dailyLossLimitEnabled", False),
            coin_has_active_trade=str(trade.symbol).upper() in open_symbols,
            stop_reentry_cooldown=same_side_stop_reentry_cooldown(
                account_trades,
                trade.symbol,
                trade.side,
            ),
        )
        for trade in trades
    ]

    records = _annotate_candidate_arbitration(records, auto, db)

    return normalized_symbol, records


def _strategy_market_participation_input(trade, payload):
    definition = strategy_definition(getattr(trade, "strategy_id", None)) or {}
    if not definition.get("requires_market_participation_confirmation", False):
        return _MARKET_PARTICIPATION_UNSET
    return payload


def _strategy_plan_risk(trade, risks_by_plan, legacy_risks_by_symbol):
    exact = risks_by_plan.get(getattr(trade, "id", None))
    if exact is not None:
        return exact
    if strategy_definition(getattr(trade, "strategy_id", None)) is not None:
        return None
    return legacy_risks_by_symbol.get(getattr(trade, "symbol", None))


def _strategy_core_signal_input(trade, payload):
    definition = strategy_definition(getattr(trade, "strategy_id", None)) or {}
    if not definition.get("requires_core_signal", False):
        return _CURRENT_SIGNAL_VALIDATION_UNSET
    return payload


def _required_current_signal_keys(trades):
    """Return unique symbol/timeframe keys that need core-signal revalidation.

    Independent strategies carry their own immutable decision snapshot and do
    not require the contradiction engine at the execution boundary.  Limiting
    this work to strategies that explicitly opt in prevents duplicate, slow
    recalculation for every competing plan while preserving the stricter gate
    for Core Signal and Core Fusion.
    """

    return {
        (
            str(getattr(trade, "symbol", "") or "").upper(),
            str(getattr(trade, "entry_timeframe", None) or "1h").lower(),
        )
        for trade in trades or []
        if (strategy_definition(getattr(trade, "strategy_id", None)) or {}).get(
            "requires_core_signal",
            False,
        )
    }


def _official_timeframe_records(records):
    return production_paper_trade_records(
        records,
        require_official_timeframe=True,
    )


def _phase2_evidence_scope():
    return {
        "market": "FUTURES",
        "mode": "intraday",
        "entry_timeframes": sorted(PHASE2_OFFICIAL_TIMEFRAMES),
        "excluded_legacy_timeframes": ["5m", "15m"],
    }


def _phase2_lifecycle_state(
    opportunity,
    plans,
    approved_candidates,
    eligible_candidates,
    open_trades,
):
    coverage = opportunity.get("coverage") or {}
    if coverage.get("status") == "GAPS_DETECTED":
        return "COVERAGE_GAP", "Recover missing scheduled opportunity evaluations."
    if open_trades:
        return "MONITORING", "Monitor open paper trades through deterministic exit handling."
    if eligible_candidates:
        return "EXECUTOR_READY", "Run the paper executor; candidate passed all current gates."
    if approved_candidates:
        return "EXECUTOR_BLOCKED", "Resolve the candidate-level executor blockers."
    if plans:
        return "RISK_PENDING", "Wait for or repair the matching risk decision."
    if opportunity.get("actionable_ready_count", 0) > 0:
        return "QUEUE_PENDING", "Persist the live READY setup as an official trade plan."
    return (
        "WAITING_FOR_READY",
        "Continue scheduled 1h/2h/4h/1d evaluation until a setup is READY.",
    )


def _phase2_open_trade_plans(plans):
    """Return the current queue, excluding closed or invalidated history."""
    return [item for item in plans or [] if item.status == "OPEN"]


def _phase2_executor_ready_candidates(candidates):
    """Use the executor's post-gate, post-arbitration selection as readiness."""
    return [
        item
        for item in candidates or []
        if (item.get("arbitration") or {}).get(
            "selected_for_official_execution"
        )
        is True
    ]


def _phase2_executor_blockers(candidates):
    """Count the complete blockers used by official paper execution."""
    return Counter(
        reason
        for item in candidates or []
        for reason in (
            (item.get("arbitration") or {}).get("executor_blockers")
            or item.get("blocked_reasons")
            or []
        )
    )


def _build_phase2_rolling_window(db, symbol, days):
    cutoff = datetime.utcnow() - timedelta(days=days)
    opportunity_records = list_decision_snapshots(
        db,
        decision_version=PHASE2_OPPORTUNITY_DECISION_VERSION,
        symbol=symbol,
        created_after=cutoff,
        limit=100000,
    )
    expected_symbols = (
        [symbol]
        if symbol
        else [item.symbol for item in SymbolRepository().get_active_symbols(db)]
    )
    opportunity = _phase2_opportunity_report(
        opportunity_records,
        symbol,
        days * 24,
        100000,
        expected_symbols,
        15,
    )

    plan_query = db.query(TradePlan).filter(TradePlan.created_at >= cutoff)
    risk_query = db.query(RiskDecision).filter(RiskDecision.created_at >= cutoff)
    trade_query = db.query(PaperTrade).filter(PaperTrade.created_at >= cutoff)
    if symbol:
        plan_query = plan_query.filter(TradePlan.symbol == symbol)
        risk_query = risk_query.filter(RiskDecision.symbol == symbol)
        trade_query = trade_query.filter(PaperTrade.symbol == symbol)

    plans = _official_timeframe_records(plan_query.all())
    risks = risk_query.all()
    trades = _official_timeframe_records(trade_query.all())
    approved_plan_count = sum(
        1
        for plan in plans
        if any(_risk_approves_plan(risk, plan) for risk in risks)
    )
    attach_scenario_context(db, trades)
    attach_regime_outcome_context(db, trades)
    measurement = build_measurement_report(trades)
    overall = measurement["overall"]
    evaluated = opportunity.get("total_evaluations", 0)
    ready = opportunity.get("ready_count", 0)
    queued = len(plans)
    executed = len(trades)
    closed = overall.get("closed_trades", 0)

    return {
        "days": days,
        "start_at": cutoff,
        "status": measurement.get("status"),
        "coverage": _rolling_coverage_summary(opportunity.get("coverage")),
        "stages": {
            "evaluated": evaluated,
            "ready": ready,
            "queued": queued,
            "risk_approved": approved_plan_count,
            "executed": executed,
            "closed": closed,
        },
        "conversion": {
            "ready_rate_percent": _conversion_percent(ready, evaluated),
            "ready_to_queue_percent": _conversion_percent(queued, ready),
            "queue_to_risk_approval_percent": _conversion_percent(
                approved_plan_count,
                queued,
            ),
            "risk_approval_to_execution_percent": _conversion_percent(
                executed,
                approved_plan_count,
            ),
            "execution_to_close_percent": _conversion_percent(closed, executed),
        },
        "performance": overall,
        "cohorts": measurement.get("cohorts"),
    }


def _risk_approves_plan(risk, plan):
    return (
        risk.decision == "APPROVE"
        and risk.signal == plan.side
        and risk.symbol == plan.symbol
        and (risk.created_at is None or plan.created_at is None or risk.created_at >= plan.created_at)
        and _same_price(risk.entry_price, plan.entry_price)
        and _same_price(risk.stop_loss, plan.stop_loss)
        and _same_price(risk.target1, plan.target1)
    )


def _conversion_percent(numerator, denominator):
    return round((numerator / denominator) * 100, 2) if denominator else None


def _rolling_coverage_summary(coverage):
    if not coverage:
        return None
    return {
        key: coverage.get(key)
        for key in (
            "status",
            "coverage_percent",
            "expected_evaluations",
            "recorded_evaluations",
            "missing_evaluations",
            "first_expected_candle",
            "latest_expected_candle",
        )
    }


def _phase2_opportunity_report(
    records,
    symbol_filter,
    since_hours,
    limit,
    expected_symbols,
    scheduler_grace_minutes,
):
    decisions = Counter()
    block_reasons = Counter()
    symbols = Counter()
    timeframes = Counter()
    latest = []

    for record in records:
        try:
            snapshot = json.loads(record.snapshot_json or "{}")
        except (TypeError, ValueError):
            snapshot = {}

        decision = (record.decision or "UNKNOWN").upper()
        decisions[decision] += 1
        symbols[record.symbol] += 1
        timeframes[record.timeframe] += 1
        context = snapshot.get("context") or {}
        failed_conditions = context.get("failed_conditions") or []
        trigger = snapshot.get("signal") or {}
        accounting_reasons = [
            reason
            for reason in failed_conditions
            if reason
        ]
        if decision != "READY" and not accounting_reasons:
            trigger_reason = context.get("trigger_reason") or trigger.get("reason")
            if trigger_reason:
                accounting_reasons.append(trigger_reason)
        block_reasons.update(accounting_reasons)
        latest.append(
            {
                "id": record.id,
                "symbol": record.symbol,
                "timeframe": record.timeframe,
                "decision": decision,
                "confidence": record.confidence,
                "regime": record.regime,
                "quality_state": record.quality_state,
                "trigger_reason": context.get("trigger_reason") or trigger.get("reason"),
                "failed_conditions": failed_conditions,
                "effective_timestamp": record.effective_timestamp,
                "recorded_at": record.created_at,
            }
        )

    total = len(records)
    ready_count = decisions.get("READY", 0)
    coverage = _phase2_opportunity_coverage(
        records,
        expected_symbols,
        scheduler_grace_minutes,
    )
    latest_expected_slot = coverage.get("latest_expected_candle")
    actionable_ready_count = sum(
        1
        for record in records
        if (record.decision or "").upper() == "READY"
        and record.effective_timestamp == latest_expected_slot
    )
    return {
        "source": "phase2_opportunity_accounting",
        "status": "OK",
        "decision_version": PHASE2_OPPORTUNITY_DECISION_VERSION,
        "evidence_scope": _phase2_evidence_scope(),
        "symbol_filter": symbol_filter,
        "window_hours": since_hours,
        "limit": limit,
        "coverage": coverage,
        "total_evaluations": total,
        "ready_count": ready_count,
        "actionable_ready_count": actionable_ready_count,
        "blocked_count": total - ready_count,
        "ready_rate_percent": round((ready_count / total) * 100, 2) if total else 0,
        "by_decision": dict(decisions),
        "by_block_reason": dict(block_reasons.most_common()),
        "by_symbol": dict(symbols),
        "by_entry_timeframe": dict(timeframes),
        "latest": latest[:100],
    }


def _phase2_opportunity_coverage(
    records,
    expected_symbols,
    scheduler_grace_minutes,
):
    expected_symbols = sorted(set(expected_symbols or []))
    eligible_records = [
        record
        for record in records
        if record.timeframe == "1h"
        and record.effective_timestamp is not None
        and record.symbol in expected_symbols
    ]

    base = {
        "scope": "ACTIVE_FUTURES_SYMBOLS_X_CLOSED_1H_CANDLES",
        "scheduler_grace_minutes": scheduler_grace_minutes,
        "expected_symbols": expected_symbols,
        "expected_symbol_count": len(expected_symbols),
    }
    if not expected_symbols:
        return {
            **base,
            "status": "NO_ACTIVE_SYMBOLS",
            "coverage_percent": 0,
            "expected_evaluations": 0,
            "recorded_evaluations": 0,
            "missing_evaluations": 0,
            "missing": [],
        }
    if not eligible_records:
        return {
            **base,
            "status": "NOT_STARTED",
            "coverage_percent": 0,
            "expected_evaluations": 0,
            "recorded_evaluations": 0,
            "missing_evaluations": 0,
            "missing": [],
        }

    first_slot = min(record.effective_timestamp for record in eligible_records)
    grace_cutoff = datetime.utcnow() - timedelta(minutes=scheduler_grace_minutes)
    latest_eligible_slot = (
        grace_cutoff.replace(minute=0, second=0, microsecond=0)
        - timedelta(hours=1)
    )
    if latest_eligible_slot < first_slot:
        return {
            **base,
            "status": "WAITING_FOR_GRACE_PERIOD",
            "coverage_percent": 100,
            "first_expected_candle": first_slot,
            "latest_expected_candle": None,
            "expected_evaluations": 0,
            "recorded_evaluations": 0,
            "missing_evaluations": 0,
            "missing": [],
        }

    expected_slots = []
    current_slot = first_slot
    while current_slot <= latest_eligible_slot:
        expected_slots.append(current_slot)
        current_slot += timedelta(hours=1)

    observed_by_slot = defaultdict(set)
    for record in eligible_records:
        observed_by_slot[record.effective_timestamp].add(record.symbol)

    missing = []
    recorded_evaluations = 0
    for slot in expected_slots:
        observed_symbols = observed_by_slot.get(slot, set())
        recorded_evaluations += len(observed_symbols.intersection(expected_symbols))
        missing_symbols = [
            symbol
            for symbol in expected_symbols
            if symbol not in observed_symbols
        ]
        if missing_symbols:
            missing.append(
                {
                    "effective_timestamp": slot,
                    "symbols": missing_symbols,
                    "missing_count": len(missing_symbols),
                }
            )

    expected_evaluations = len(expected_slots) * len(expected_symbols)
    missing_evaluations = max(0, expected_evaluations - recorded_evaluations)
    coverage_percent = (
        round((recorded_evaluations / expected_evaluations) * 100, 2)
        if expected_evaluations
        else 100
    )
    return {
        **base,
        "status": "COMPLETE" if missing_evaluations == 0 else "GAPS_DETECTED",
        "coverage_percent": coverage_percent,
        "first_expected_candle": first_slot,
        "latest_expected_candle": latest_eligible_slot,
        "expected_candle_count": len(expected_slots),
        "expected_evaluations": expected_evaluations,
        "recorded_evaluations": recorded_evaluations,
        "missing_evaluations": missing_evaluations,
        "missing": missing[:100],
    }


def _find_phase2_checkpoint(records, checkpoint_date):
    return next(
        (
            record
            for record in records
            if (record.get("details") or {}).get("checkpoint_date") == checkpoint_date
        ),
        None,
    )


def record_phase2_evidence_checkpoint(
    db,
    *,
    checkpoint_date=None,
    observed_at=None,
):
    """Persist at most one Phase 2 evidence checkpoint per UTC date."""
    checkpoint_date = str(
        checkpoint_date or datetime.utcnow().date().isoformat()
    )[:10]
    event_repo = DataQualityEventRepository()
    existing = _find_phase2_checkpoint(
        event_repo.list_events(
            db,
            source=PHASE2_CHECKPOINT_EVENT_SOURCE,
            category=PHASE2_CHECKPOINT_EVENT_CATEGORY,
            limit=500,
        ),
        checkpoint_date,
    )
    if existing:
        return {
            "source": "phase2_daily_evidence_checkpoint",
            "status": "EXISTS",
            "record": existing,
        }

    checkpoint = _build_phase2_evidence_checkpoint(db, checkpoint_date)
    records = event_repo.record_events(
        db,
        [
            {
                "symbol": "SYSTEM",
                "timeframe": "1d",
                "source": PHASE2_CHECKPOINT_EVENT_SOURCE,
                "category": PHASE2_CHECKPOINT_EVENT_CATEGORY,
                "severity": (
                    "error" if checkpoint["status"] == "ATTENTION" else "info"
                ),
                "status": checkpoint["status"],
                "blocked": checkpoint["status"] == "ATTENTION",
                "reason": checkpoint["reason"],
                "details": checkpoint,
                "observed_at": observed_at,
                "effective_at": observed_at,
            }
        ],
    )
    return {
        "source": "phase2_daily_evidence_checkpoint",
        "status": "RECORDED",
        "record": records[0] if records else None,
    }


def _build_phase2_evidence_checkpoint(db, checkpoint_date):
    created_after = datetime.utcnow() - timedelta(hours=24)
    opportunity_records = list_decision_snapshots(
        db,
        decision_version=PHASE2_OPPORTUNITY_DECISION_VERSION,
        created_after=created_after,
        limit=10000,
    )
    expected_symbols = [
        item.symbol
        for item in SymbolRepository().get_active_symbols(db)
    ]
    opportunity = _phase2_opportunity_report(
        opportunity_records,
        None,
        24,
        10000,
        expected_symbols,
        15,
    )

    recovery_records = DataQualityEventRepository().list_events(
        db,
        source=PHASE2_RECOVERY_EVENT_SOURCE,
        category=PHASE2_RECOVERY_EVENT_CATEGORY,
        limit=500,
    )
    recovery_outcomes = Counter(item["status"] for item in recovery_records)

    measurement = _build_phase2_checkpoint_measurement(db)
    overall = measurement.get("overall") or {}
    coverage = opportunity.get("coverage") or {}

    if coverage.get("status") == "GAPS_DETECTED" or measurement.get("status") == "FAIL":
        status = "ATTENTION"
        reason = "Phase 2 evidence requires attention."
    elif measurement.get("status") == "PASS" and coverage.get("status") == "COMPLETE":
        status = "PASS"
        reason = "Phase 2 daily evidence meets current promotion gates."
    else:
        status = "PENDING"
        reason = "Phase 2 evidence is accumulating and has not reached promotion depth."

    return {
        "checkpoint_date": checkpoint_date,
        "status": status,
        "reason": reason,
        "generated_at": datetime.utcnow(),
        "evidence_scope": _phase2_evidence_scope(),
        "opportunity": {
            "total_evaluations": opportunity.get("total_evaluations", 0),
            "ready_count": opportunity.get("ready_count", 0),
            "blocked_count": opportunity.get("blocked_count", 0),
            "ready_rate_percent": opportunity.get("ready_rate_percent", 0),
            "by_block_reason": opportunity.get("by_block_reason") or {},
            "coverage": coverage,
        },
        "recovery": {
            "event_count": len(recovery_records),
            "attempts": recovery_outcomes.get("ATTEMPTED", 0),
            "recovered": recovery_outcomes.get("RECOVERED", 0),
            "unresolved": recovery_outcomes.get("UNRESOLVED", 0),
            "retry_failed": recovery_outcomes.get("RETRY_FAILED", 0),
            "latest": recovery_records[0] if recovery_records else None,
        },
        "measurement": {
            "status": measurement.get("status"),
            "closed_trades": overall.get("closed_trades", 0),
            "observation_days": overall.get("observation_days", 0),
            "wins": overall.get("wins", 0),
            "losses": overall.get("losses", 0),
            "win_rate": overall.get("win_rate", 0),
            "profit_factor": overall.get("profit_factor"),
            "expectancy_percent": overall.get("expectancy_percent", 0),
            "compounded_return_percent": overall.get("compounded_return_percent", 0),
            "max_drawdown_percent": overall.get("max_drawdown_percent", 0),
            "payoff_ratio": overall.get("payoff_ratio"),
            "evaluation": measurement.get("evaluation") or {},
        },
    }


def _build_phase2_checkpoint_measurement(db):
    """Build only the aggregate metrics stored by the daily checkpoint.

    Scenario and realized-regime enrichment are intentionally omitted here:
    the checkpoint does not persist those cohorts, and resolving a regime per
    closed trade creates an expensive N+1 query on the worker's shared DB.
    """
    trades = _official_timeframe_records(PaperTradeRepository().all_trades(db))
    return build_measurement_report(trades, gates=MeasurementGates())


def _paper_trade_payload(paper_trade, fill_profile=None):
    exit_levels = _paper_trade_display_exit_levels(paper_trade)
    remaining_fraction = getattr(
        paper_trade,
        "remaining_position_fraction",
        None,
    )
    if remaining_fraction is None:
        remaining_fraction = exit_levels.get("remaining_position_fraction")
    sizing = build_inr_paper_sizing(
        paper_trade.confidence or 0,
        fee_bps=paper_trade.fee_bps or DEFAULT_FEE_BPS,
        remaining_fraction=(
            1.0 if remaining_fraction is None else remaining_fraction
        ),
    )
    persisted_margin = getattr(paper_trade, "margin_used_inr", None)
    if (
        persisted_margin is not None
        and float(persisted_margin) < float(sizing["margin_used_inr"])
    ):
        sizing = fit_inr_paper_sizing_to_margin_capacity(
            sizing,
            float(persisted_margin),
        )
    sizing.update(
        {
            "paper_capital_inr": getattr(
                paper_trade,
                "paper_capital_at_entry_inr",
                None,
            )
            or sizing["paper_capital_inr"],
            "allocation_percent": getattr(
                paper_trade,
                "allocation_percent",
                None,
            )
            or sizing["allocation_percent"],
            "position_notional_inr": getattr(
                paper_trade,
                "position_notional_inr",
                None,
            )
            or sizing["position_notional_inr"],
            "leverage": getattr(paper_trade, "leverage", None)
            or sizing["leverage"],
            "margin_used_inr": persisted_margin or sizing["margin_used_inr"],
        }
    )
    payload = {
        "id": paper_trade.id,
        "trade_plan_id": paper_trade.trade_plan_id,
        "risk_decision_id": paper_trade.risk_decision_id,
        "thesis_id": getattr(paper_trade, "thesis_id", None),
        "symbol": paper_trade.symbol,
        "side": paper_trade.side,
        "entry_price": paper_trade.entry_price,
        "stop_loss": exit_levels["stop_loss"],
        "target1": exit_levels["target1"],
        "target2": exit_levels["target2"],
        "position_size": paper_trade.position_size,
        "risk_reward": paper_trade.risk_reward,
        "risk_percent": paper_trade.risk_percent,
        "confidence": paper_trade.confidence,
        "mode": paper_trade.mode,
        "entry_timeframe": paper_trade.entry_timeframe,
        "timeframe_stack": paper_trade.timeframe_stack,
        "regime": paper_trade.regime,
        "data_generation_id": getattr(paper_trade, "data_generation_id", None),
        "strategy_id": getattr(paper_trade, "strategy_id", None),
        "strategy_version": getattr(paper_trade, "strategy_version", None),
        "strategy_decision_snapshot_id": getattr(
            paper_trade,
            "strategy_decision_snapshot_id",
            None,
        ),
        "exit_policy": exit_levels["exit_policy"],
        "exit_levels_source": exit_levels["source"],
        "initial_stop_loss": exit_levels["initial_stop_loss"],
        "target1_fraction": exit_levels["target1_fraction"],
        "remaining_position_fraction": remaining_fraction,
        "max_hold_hours": exit_levels["max_hold_hours"],
        "target1_hit_at": getattr(paper_trade, "target1_hit_at", None),
        "target1_exit_price": getattr(paper_trade, "target1_exit_price", None),
        "exit_monitor_timeframe": getattr(
            paper_trade,
            "exit_monitor_timeframe",
            None,
        ),
        "last_exit_evaluated_at": getattr(
            paper_trade,
            "last_exit_evaluated_at",
            None,
        ),
        "validation_contract_version": getattr(
            paper_trade,
            "validation_contract_version",
            None,
        ),
        "fill_model_version": getattr(paper_trade, "fill_model_version", None),
        "planned_entry_price": getattr(paper_trade, "planned_entry_price", None),
        "entry_slippage_percent": getattr(
            paper_trade,
            "entry_slippage_percent",
            None,
        ),
        "exit_slippage_percent": getattr(
            paper_trade,
            "exit_slippage_percent",
            None,
        ),
        "funding_rate_snapshot": getattr(
            paper_trade,
            "funding_rate_snapshot",
            None,
        ),
        "funding_event_count": getattr(
            paper_trade,
            "funding_event_count",
            None,
        ),
        "funding_cost_percent": getattr(
            paper_trade,
            "funding_cost_percent",
            None,
        ),
        "open_interest_snapshot": getattr(
            paper_trade,
            "open_interest_snapshot",
            None,
        ),
        "open_interest_change_percent": getattr(
            paper_trade,
            "open_interest_change_percent",
            None,
        ),
        "fee_bps": paper_trade.fee_bps,
        "fees_percent": paper_trade.fees_percent,
        "gross_pnl_percent": paper_trade.gross_pnl_percent,
        "status": paper_trade.status,
        "exit_price": paper_trade.exit_price,
        "exit_reason": getattr(paper_trade, "exit_reason", None),
        "result": paper_trade.result,
        "pnl_percent": paper_trade.pnl_percent,
        "partial_realized_pnl_inr": getattr(
            paper_trade,
            "partial_realized_pnl_inr",
            None,
        ),
        "realized_pnl_inr": getattr(paper_trade, "realized_pnl_inr", None),
        "opened_at": paper_trade.opened_at,
        "closed_at": paper_trade.closed_at,
        "created_at": paper_trade.created_at,
        "market_type": "FUTURES",
        "instrument_type": "PERPETUAL",
        "venue": "COINDCX_INR_M_PAPER",
        "price_reference_venue": "BINANCE_FUTURES",
        "paper_sizing": sizing,
        "currency": sizing["currency"],
        "position_notional_inr": sizing["position_notional_inr"],
        "margin_used_inr": sizing["margin_used_inr"],
        "allocation_percent": sizing["allocation_percent"],
        "leverage": sizing["leverage"],
    }

    if fill_profile is not None:
        payload["fill_profile"] = fill_profile

    return payload


def _paper_trade_display_exit_levels(paper_trade):
    """Return complete display levels for official open paper positions.

    The monitor persists the staged-exit policy before evaluating a trade. This
    read-side fallback keeps older open rows understandable during the short
    window before that repair runs, without changing closed-trade evidence.
    """
    persisted = {
        "stop_loss": getattr(paper_trade, "stop_loss", None),
        "target1": getattr(paper_trade, "target1", None),
        "target2": getattr(paper_trade, "target2", None),
        "exit_policy": getattr(paper_trade, "exit_policy", None),
        "initial_stop_loss": getattr(paper_trade, "initial_stop_loss", None),
        "target1_fraction": getattr(paper_trade, "target1_fraction", None),
        "remaining_position_fraction": getattr(
            paper_trade,
            "remaining_position_fraction",
            None,
        ),
        "max_hold_hours": getattr(paper_trade, "max_hold_hours", None),
        "source": "PERSISTED",
    }
    required = ("stop_loss", "target1", "target2", "exit_policy", "max_hold_hours")
    if str(getattr(paper_trade, "status", "") or "").upper() != "OPEN":
        return persisted
    if all(persisted[key] is not None for key in required):
        return persisted

    entry_price = getattr(paper_trade, "entry_price", None)
    if entry_price is None:
        return persisted
    policy = build_policy_trade_levels(
        getattr(paper_trade, "side", None),
        entry_price,
        symbol=getattr(paper_trade, "symbol", None),
        timeframe=getattr(paper_trade, "entry_timeframe", None),
        confidence=getattr(paper_trade, "confidence", None) or 0,
        fee_bps=getattr(paper_trade, "fee_bps", None) or DEFAULT_FEE_BPS,
        price_precision=_paper_trade_price_precision(entry_price),
    )
    if policy is None:
        return persisted

    target1_complete = getattr(paper_trade, "target1_hit_at", None) is not None
    persisted_fraction = persisted.get("target1_fraction")
    target1_fraction = (
        float(persisted_fraction)
        if target1_complete and persisted_fraction is not None
        else policy["target1_fraction"]
    )
    fallback = {
        "stop_loss": (
            target1_protection_stop(
                getattr(paper_trade, "side", None),
                entry_price,
                policy["target1"],
                _paper_trade_price_precision(entry_price),
            )
            if target1_complete
            else policy["stop_loss"]
        ),
        "target1": policy["target1"],
        "target2": policy["target2"],
        "exit_policy": policy["name"],
        "initial_stop_loss": policy["stop_loss"],
        "target1_fraction": target1_fraction,
        "remaining_position_fraction": (
            1.0 - target1_fraction if target1_complete else 1.0
        ),
        "max_hold_hours": policy["max_hold_hours"],
    }
    return {
        key: persisted[key] if persisted.get(key) is not None else value
        for key, value in fallback.items()
    } | {"source": "POLICY_FALLBACK"}


def _paper_trade_price_precision(price):
    price = float(price)
    if price < 1:
        return 6
    if price < 10:
        return 5
    if price < 100:
        return 4
    return 2


def _summarize_paper_trades(records):
    return {
        "open": sum(1 for item in records if item["status"] == "OPEN"),
        "closed": sum(1 for item in records if item["status"] == "CLOSED"),
        "wins": sum(1 for item in records if item["result"] == "WIN"),
        "losses": sum(1 for item in records if item["result"] == "LOSS"),
    }


def _paper_trade_candidate(
    trade,
    risk,
    stale_after_seconds,
    derivatives=None,
    *,
    market_participation=_MARKET_PARTICIPATION_UNSET,
    current_signal_validation=_CURRENT_SIGNAL_VALIDATION_UNSET,
    account_risk=None,
    paper_wallet=None,
    max_open_trades=4,
    max_open_trades_enabled=False,
    daily_loss_limit_enabled=False,
    coin_has_active_trade=False,
    stop_reentry_cooldown=None,
    strategy_snapshot=None,
    strategy_definition_override=None,
):
    risk_payload = _risk_decision_payload(risk, stale_after_seconds)
    planned_stop_percent = (
        abs(float(trade.entry_price) - float(trade.stop_loss))
        / float(trade.entry_price)
        * 100
        if trade.entry_price and trade.stop_loss is not None
        else 0.75
    )
    paper_sizing = build_inr_paper_sizing(
        risk_payload.get("confidence", trade.confidence or 0),
        fee_bps=DEFAULT_FEE_BPS,
        stop_loss_percent=planned_stop_percent,
    )
    fill_profile = build_fill_profile(
        side=trade.side,
        planned_entry_price=trade.entry_price,
        stop_loss=trade.stop_loss,
        target1=approval_target_for_policy(
            getattr(trade, "exit_policy", None),
            trade.target1,
            trade.target2,
        ),
        confidence=risk_payload.get("confidence", trade.confidence or 50),
        risk_reward=trade.risk_reward,
    )
    trade_blockers = _paper_trade_blocked_reasons(
        trade,
        risk,
        risk_payload,
        derivatives,
        fill_profile=fill_profile,
        strategy_snapshot=strategy_snapshot,
        strategy_definition_override=strategy_definition_override,
    )
    if market_participation is not _MARKET_PARTICIPATION_UNSET:
        trade_blockers.extend(
            _market_participation_blockers(
                market_participation,
                trade.side,
            )
        )
    if current_signal_validation is not _CURRENT_SIGNAL_VALIDATION_UNSET:
        trade_blockers.extend(
            _current_signal_blockers(current_signal_validation, trade.side)
        )
    coin_blockers = []
    if coin_has_active_trade:
        coin_blockers.append("Active trade already exists for this coin")
    if (stop_reentry_cooldown or {}).get("active"):
        coin_blockers.append(PAPER_STOP_REENTRY_COOLDOWN_REASON)
    account_blockers = []
    if not account_risk or not account_risk.get("risk_available", False):
        account_blockers.append("Account-wide risk valuation is unavailable or stale")
    elif daily_loss_limit_enabled and account_risk.get("limit_reached"):
        account_blockers.append("Account-wide daily loss limit reached")
    if max_open_trades_enabled and int(
        (paper_wallet or {}).get("open_position_count") or 0
    ) >= int(max_open_trades):
        account_blockers.append("Account-wide open trade cap reached")
    remaining_margin_capacity = (paper_wallet or {}).get(
        "remaining_margin_capacity_inr"
    )
    if remaining_margin_capacity is not None and float(remaining_margin_capacity) > 0:
        paper_sizing = fit_inr_paper_sizing_to_margin_capacity(
            paper_sizing,
            float(remaining_margin_capacity),
        )
    if (
        remaining_margin_capacity is not None
        and paper_sizing["margin_used_inr"] > float(remaining_margin_capacity)
    ):
        account_blockers.append("INR paper-wallet margin cap reached")
    blocker_scopes = {
        "trade": trade_blockers,
        "coin": coin_blockers,
        "account": account_blockers,
    }
    blocked_reasons = trade_blockers + coin_blockers + account_blockers

    return {
        "symbol": trade.symbol,
        "side": trade.side,
        "eligible": not blocked_reasons,
        "blocked_reasons": blocked_reasons,
        "blocker_scopes": blocker_scopes,
        "account_risk": account_risk,
        "stop_reentry_cooldown": stop_reentry_cooldown,
        "validation_contract_version": PHASE2_VALIDATION_CONTRACT_VERSION,
        "trade_plan": _trade_plan_payload(trade),
        "risk_decision": risk_payload,
        "paper_sizing": paper_sizing,
        "fill_profile": fill_profile,
        "market_participation": (
            None
            if market_participation is _MARKET_PARTICIPATION_UNSET
            else market_participation
        ),
        "current_signal_validation": (
            None
            if current_signal_validation is _CURRENT_SIGNAL_VALIDATION_UNSET
            else current_signal_validation
        ),
        "market_context": _market_context_payload(trade.symbol, derivatives),
    }


def _current_signal_validation(db, symbol, timeframe, fallback_stale_after_seconds):
    freshness_window = stale_after_seconds_for_timeframe(
        timeframe,
        fallback=fallback_stale_after_seconds,
    )
    try:
        return build_contradiction_report(
            db,
            symbol,
            timeframe,
            freshness_window,
        )
    except SQLAlchemyError:
        db.rollback()
    except Exception:
        pass
    return {
        "source": "contradiction_engine",
        "symbol": symbol,
        "timeframe": timeframe,
        "status": "UNAVAILABLE",
        "trade_allowed": False,
        "signal": "NO_DATA",
        "reasons": ["Current signal validation is unavailable"],
    }


def _current_signal_blockers(validation, planned_side):
    validation = validation or {}
    reasons = []
    status = str(validation.get("status") or "UNAVAILABLE").upper()
    if validation.get("trade_allowed") is False or status in {
        "INVALIDATED",
        "FAILED",
        "ERROR",
        "UNAVAILABLE",
    }:
        reported = validation.get("reasons") or []
        reasons.append(
            str(reported[0])
            if reported
            else str(validation.get("summary") or "Current signal is invalidated")
        )

    current_side = _normalized_signal_side(validation.get("signal"))
    expected_side = _normalized_signal_side(planned_side)
    if not reasons and current_side != expected_side:
        reasons.append(
            f"Current signal {current_side or 'WAIT'} does not match queued "
            f"{expected_side or planned_side} trade plan"
        )
    return reasons


def _normalized_signal_side(value):
    normalized = str(value or "").upper()
    if normalized in {"LONG", "BUY", "STRONG_LONG"}:
        return "LONG"
    if normalized in {"SHORT", "SELL", "STRONG_SHORT"}:
        return "SHORT"
    return None


def _market_participation_blockers(payload, side):
    return market_participation_blockers(payload, side)


def _trade_plan_payload(trade):
    return {
        "id": trade.id,
        "thesis_id": getattr(trade, "thesis_id", None),
        "status": trade.status,
        "entry_price": trade.entry_price,
        "stop_loss": trade.stop_loss,
        "target1": trade.target1,
        "target2": trade.target2,
        "target3": trade.target3,
        "risk_reward": trade.risk_reward,
        "confidence": trade.confidence,
        "mode": getattr(trade, "mode", None),
        "entry_timeframe": getattr(trade, "entry_timeframe", None),
        "timeframe_stack": getattr(trade, "timeframe_stack", None),
        "regime": getattr(trade, "regime", None),
        "data_generation_id": getattr(trade, "data_generation_id", None),
        "strategy_id": getattr(trade, "strategy_id", None),
        "strategy_version": getattr(trade, "strategy_version", None),
        "strategy_decision_snapshot_id": getattr(
            trade,
            "strategy_decision_snapshot_id",
            None,
        ),
        "exit_policy": getattr(trade, "exit_policy", None),
        "target1_fraction": getattr(trade, "target1_fraction", None),
        "max_hold_hours": getattr(trade, "max_hold_hours", None),
        "created_at": trade.created_at,
    }


def _risk_decision_payload(risk, stale_after_seconds):
    if risk is None:
        return {
            "decision": "NO_RISK_DECISION",
            "freshness": freshness_status(None, stale_after_seconds),
        }

    sizing_profile = confidence_sizing_profile(
        risk.confidence or 0,
        risk.risk_percent or 1.0,
    )
    if str(risk.decision or "").upper() != "APPROVE":
        sizing_profile["position_tier"] = None

    return {
        "id": risk.id,
        "signal": risk.signal,
        "decision": risk.decision,
        "reason": _risk_reason(risk),
        "entry_price": risk.entry_price,
        "stop_loss": risk.stop_loss,
        "target1": risk.target1,
        "target2": risk.target2,
        "risk_reward": risk.risk_reward,
        "position_size": risk.position_size,
        "risk_percent": risk.risk_percent,
        "position_tier": sizing_profile["position_tier"],
        "full_size_confidence": risk_engine.FULL_SIZE_CONFIDENCE,
        "confidence": risk.confidence,
        "trade_plan_id": getattr(risk, "trade_plan_id", None),
        "strategy_id": getattr(risk, "strategy_id", None),
        "strategy_version": getattr(risk, "strategy_version", None),
        "strategy_decision_snapshot_id": getattr(
            risk,
            "strategy_decision_snapshot_id",
            None,
        ),
        "created_at": risk.created_at,
        "freshness": freshness_status(risk.created_at, stale_after_seconds),
    }


def _paper_trade_blocked_reasons(
    trade,
    risk,
    risk_payload,
    derivatives=None,
    fill_profile=None,
    strategy_snapshot=None,
    strategy_definition_override=None,
):
    reasons = []

    if risk is None:
        return ["No risk decision found for trade plan"]

    plan_strategy_id = getattr(trade, "strategy_id", None)
    plan_strategy_version = getattr(trade, "strategy_version", None)
    plan_strategy_snapshot_id = getattr(
        trade,
        "strategy_decision_snapshot_id",
        None,
    )
    definition = strategy_definition_override or strategy_definition(plan_strategy_id)
    if (
        definition is None
        or definition.get("status") != "ACTIVE"
        or definition.get("execution_scope") != "PAPER_ONLY"
        or definition.get("version") != plan_strategy_version
    ):
        reasons.append("Trade plan strategy is not enabled for paper execution")
    if plan_strategy_snapshot_id is None:
        reasons.append("Trade plan has no strategy decision snapshot")
    elif strategy_snapshot is None:
        reasons.append("Strategy decision snapshot was not found")
    else:
        snapshot_checks = (
            (
                getattr(strategy_snapshot, "id", None) == plan_strategy_snapshot_id,
                "Strategy decision snapshot ID does not match trade plan",
            ),
            (
                getattr(strategy_snapshot, "strategy_id", None)
                == plan_strategy_id,
                "Strategy decision snapshot strategy does not match trade plan",
            ),
            (
                getattr(strategy_snapshot, "strategy_version", None)
                == plan_strategy_version,
                "Strategy decision snapshot version does not match trade plan",
            ),
            (
                definition is not None
                and getattr(strategy_snapshot, "decision_version", None)
                == definition.get("decision_version"),
                "Strategy decision snapshot contract is not executable",
            ),
            (
                str(getattr(strategy_snapshot, "symbol", "")).upper()
                == str(getattr(trade, "symbol", "")).upper(),
                "Strategy decision snapshot coin does not match trade plan",
            ),
            (
                str(getattr(strategy_snapshot, "timeframe", "")).lower()
                == str(getattr(trade, "entry_timeframe", "")).lower(),
                "Strategy decision snapshot timeframe does not match trade plan",
            ),
            (
                str(getattr(strategy_snapshot, "decision", "")).upper()
                == "ELIGIBLE",
                "Strategy decision snapshot is not ELIGIBLE",
            ),
        )
        reasons.extend(message for valid, message in snapshot_checks if not valid)

    if risk.decision != "APPROVE":
        rejection_reason = _risk_reason(risk)
        if rejection_reason:
            reasons.append(
                f"Risk decision is not APPROVE: {risk.decision} ({rejection_reason})"
            )
        else:
            reasons.append(f"Risk decision is not APPROVE: {risk.decision}")

    if risk_payload["freshness"]["is_stale"]:
        reasons.append("Risk decision is stale")

    if risk.signal != trade.side:
        reasons.append("Risk signal does not match trade side")

    if getattr(risk, "trade_plan_id", None) != getattr(trade, "id", None):
        reasons.append("Risk decision does not match the exact trade plan")

    for field, label in (
        ("strategy_id", "strategy"),
        ("strategy_version", "strategy version"),
        ("strategy_decision_snapshot_id", "strategy decision snapshot"),
    ):
        plan_value = getattr(trade, field, None)
        risk_value = getattr(risk, field, None)
        if risk_value != plan_value:
            reasons.append(f"Risk {label} does not match trade plan")

    if not _same_price(risk.entry_price, trade.entry_price):
        reasons.append("Risk entry does not match trade entry")

    if not _same_price(risk.stop_loss, trade.stop_loss):
        reasons.append("Risk stop_loss does not match trade stop_loss")

    if not _same_price(risk.target1, trade.target1):
        reasons.append("Risk target1 does not match trade target1")

    if trade.created_at and risk.created_at and risk.created_at < trade.created_at:
        reasons.append("Risk decision is older than trade plan")

    effective_rr = (fill_profile or {}).get("effective_risk_reward")
    if effective_rr is None or float(effective_rr) < risk_engine.MIN_RISK_REWARD:
        reasons.append(
            "Net risk reward is below 2.0 after estimated futures fees and slippage"
        )

    return reasons


def _market_context_payload(symbol=None, derivatives=None):
    availability = (derivatives or {}).get("availability") or {}
    funding_available = bool(availability.get("funding"))
    open_interest_available = bool(availability.get("open_interest"))
    return {
        "symbol": symbol,
        "market_type": "FUTURES",
        "instrument_type": "PERPETUAL",
        "venue": "BINANCE_FUTURES",
        "paper_execution_venue": "COINDCX_INR_M_PAPER",
        "margin_currency": "INR",
        "fundingRate": (derivatives or {}).get("latest_funding_rate"),
        "openInterest": (derivatives or {}).get("latest_open_interest"),
        "openInterestChangePercent": (derivatives or {}).get(
            "latest_open_interest_change_pct"
        ),
        "fundingAvailable": funding_available,
        "openInterestAvailable": open_interest_available,
        "isReady": funding_available and open_interest_available,
    }


def _safe_derivatives_payload(db, symbol, stale_after_seconds):
    try:
        return build_derivatives_payload(
            db,
            symbol,
            stale_after_seconds=stale_after_seconds,
        )
    except SQLAlchemyError:
        db.rollback()
        return {}


def _same_price(left, right):
    if left is None or right is None:
        return False

    return abs(float(left) - float(right)) <= 0.00000001


def _finite_float(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _risk_reason(risk):
    stored_reason = getattr(risk, "reason", None)

    if stored_reason:
        return stored_reason

    if str(getattr(risk, "decision", "") or "").upper() != "REJECT":
        return None

    try:
        recomputed = risk_engine.analyze_trade_plan(
            symbol=risk.symbol,
            side=risk.signal,
            entry=risk.entry_price,
            stop_loss=risk.stop_loss,
            target1=risk.target1,
            target2=risk.target2,
            confidence=risk.confidence or 0,
            risk_percent=risk.risk_percent or 1,
            fee_bps=DEFAULT_FEE_BPS,
        )
    except Exception:
        return None

    return recomputed.get("reason")


def _paper_trade_unavailable_payload(operation, symbol_filter=None, status_filter=None, detail="Paper-trade data is unavailable because the database is not reachable."):
    normalized_symbol = symbol_filter.upper() if symbol_filter else None
    payload = {
        "source": f"paper_trade_{operation}_fallback",
        "database_status": "UNAVAILABLE",
        "message": detail,
    }

    if normalized_symbol is not None:
        payload["symbol_filter"] = normalized_symbol

    if status_filter is not None:
        payload["status_filter"] = status_filter

    if operation == "performance":
        payload["performance"] = {
            "total_trades": 0,
            "open_trades": 0,
            "closed_trades": 0,
            "wins": 0,
            "losses": 0,
            "long_trades": 0,
            "short_trades": 0,
            "win_rate": 0,
            "average_pnl_percent": 0,
            "total_pnl_percent": 0,
        }
    elif operation == "trades":
        payload.update(
            {
                "count": 0,
                "summary": {"open": 0, "closed": 0, "wins": 0, "losses": 0},
                "records": [],
            }
        )
    elif operation == "candidates":
        payload.update(
            {
                "count": 0,
                "eligible_count": 0,
                "blocked_count": 0,
                "records": [],
            }
        )
    elif operation == "bundle":
        payload.update(
            {
                "performance": {
                    "total_trades": 0,
                    "open_trades": 0,
                    "closed_trades": 0,
                    "wins": 0,
                    "losses": 0,
                    "long_trades": 0,
                    "short_trades": 0,
                    "win_rate": 0,
                    "average_pnl_percent": 0,
                    "total_pnl_percent": 0,
                },
                "summary": {"open": 0, "closed": 0, "wins": 0, "losses": 0},
                "paperWallet": build_inr_paper_wallet([]),
                "openTrades": {"count": 0, "records": []},
                "closedTrades": {"count": 0, "records": []},
            }
        )
    elif operation == "measurement":
        payload["report"] = build_measurement_report([])

    return payload


def _paper_trade_execution_unavailable_payload(symbol_filter=None, detail="Paper-trade execution is unavailable because the database is not reachable."):
    normalized_symbol = symbol_filter.upper() if symbol_filter else None
    payload = {
        "source": "paper_trade_execution_simulator_fallback",
        "database_status": "UNAVAILABLE",
        "message": detail,
        "symbol_filter": normalized_symbol,
        "candidate_count": 0,
        "executed_count": 0,
        "skipped_count": 0,
        "executed": [],
        "skipped": [],
    }
    return payload
