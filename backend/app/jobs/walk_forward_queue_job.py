"""Worker-side scheduler and processor for durable walk-forward validation."""

import json
from datetime import datetime, timezone

from sqlalchemy import func

from app.backtesting.walk_forward_jobs import claim_next_walk_forward_job
from app.backtesting.walk_forward_jobs import create_automatic_walk_forward_job
from app.backtesting.walk_forward_jobs import load_walk_forward_job
from app.backtesting.walk_forward_validator import PHASE2_OFFICIAL_TIMEFRAMES
from app.backtesting.walk_forward_validator import PHASE2_WALK_FORWARD_DAYS
from app.backtesting.walk_forward_validator import minimum_candles_for_folds
from app.backtesting.walk_forward_validator import phase2_walk_forward_defaults
from app.database.models.point_in_time_snapshots import DecisionSnapshot
from app.database.sqlserver import SessionLocal
from app.repositories.master_signal_repository import MasterSignalRepository
from app.repositories.symbol_repository import SymbolRepository
from app.strategies.registry import CORE_SIGNAL_DECISION_VERSION
from app.strategies.registry import CORE_SIGNAL_STRATEGY_ID
from app.trading.futures_cost_model import DEFAULT_FEE_BPS


AUTOMATIC_MIN_CONFIDENCE = 40.0
AUTOMATIC_DECISION_MAX_AGE_SECONDS = 10 * 60
AUTOMATIC_REFRESH_SECONDS = {
    "1h": 6 * 60 * 60,
    "2h": 12 * 60 * 60,
    "4h": 24 * 60 * 60,
    "1d": 24 * 60 * 60,
}
TIMEFRAME_SECONDS = {
    "1h": 60 * 60,
    "2h": 2 * 60 * 60,
    "4h": 4 * 60 * 60,
    "1d": 24 * 60 * 60,
}


def run_walk_forward_queue_job():
    record = claim_next_walk_forward_job()
    scheduled = None
    scheduling_error = None
    if record is None:
        try:
            scheduled = _enqueue_next_automatic_walk_forward_job()
        except Exception as exc:
            # Automatic validation must never stop the rest of the worker.
            scheduling_error = str(exc)[:500]
        if scheduled is not None:
            record = claim_next_walk_forward_job()
    if record is None:
        return {
            "source": "walk_forward_worker_queue_v1",
            "status": "IDLE",
            "job_id": None,
            "automatic_scheduling_error": scheduling_error,
        }

    # Imported lazily to keep scheduler discovery independent from API startup
    # and to reuse the same governed replay/report implementation.
    from app.api.v1.backtest_api import _run_walk_forward_validation_job

    _run_walk_forward_validation_job(record["job_id"], record["parameters"])
    completed = load_walk_forward_job(record["job_id"])
    return {
        "source": "walk_forward_worker_queue_v1",
        "status": (completed or {}).get("status") or "UNKNOWN",
        "job_id": record["job_id"],
        "error": (completed or {}).get("error"),
        "automatic": scheduled is not None,
    }


def _enqueue_next_automatic_walk_forward_job(*, now=None):
    """Queue at most one due, fresh, directional validation per worker tick."""

    checked_at = _utc_now(now)
    db = SessionLocal()
    try:
        symbols = [
            str(item.symbol).strip().upper()
            for item in SymbolRepository().get_active_symbols(db)
        ]
        if not symbols:
            return None
        snapshot_ids = (
            db.query(func.max(DecisionSnapshot.id).label("snapshot_id"))
            .filter(DecisionSnapshot.strategy_id == CORE_SIGNAL_STRATEGY_ID)
            .filter(
                DecisionSnapshot.decision_version
                == CORE_SIGNAL_DECISION_VERSION
            )
            .filter(DecisionSnapshot.symbol.in_(symbols))
            .group_by(DecisionSnapshot.symbol)
            .subquery()
        )
        snapshots = (
            db.query(DecisionSnapshot)
            .join(
                snapshot_ids,
                snapshot_ids.c.snapshot_id == DecisionSnapshot.id,
            )
            .all()
        )
        covered_symbols = {
            str(item.symbol).strip().upper() for item in snapshots
        }
        fallback_symbols = [
            symbol for symbol in symbols if symbol not in covered_symbols
        ]
        signals = (
            MasterSignalRepository().get_latest_signals(
                db,
                symbols=fallback_symbols,
            )
            if fallback_symbols
            else []
        )
        candidates = _snapshot_candidates(snapshots, checked_at)
        candidates.extend(_legacy_signal_candidates(signals, checked_at))
    finally:
        db.close()

    # Prefer the freshest, strongest signal. Due checks below prevent one scope
    # from starving other symbols/timeframes.
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    for _created_at, _confidence, symbol, side, timeframe in candidates:
        parameters = _automatic_parameters(symbol, timeframe, side)
        record, created = create_automatic_walk_forward_job(
            parameters,
            refresh_after_seconds=AUTOMATIC_REFRESH_SECONDS[timeframe],
            now=checked_at,
        )
        if created:
            return record
    return None


def _snapshot_candidates(snapshots, checked_at):
    """Build validation scopes from the worker's governed Core Signal output."""

    candidates = []
    for row in snapshots:
        timeframe = str(getattr(row, "timeframe", "") or "").strip().lower()
        confidence = _number(getattr(row, "confidence", None))
        created_at = getattr(row, "created_at", None)
        side = _snapshot_side(row)
        if str(getattr(row, "decision", "") or "").upper() != "ELIGIBLE":
            continue
        if timeframe not in PHASE2_OFFICIAL_TIMEFRAMES or side is None:
            continue
        if confidence is None or confidence < AUTOMATIC_MIN_CONFIDENCE:
            continue
        if not _is_recent(created_at, AUTOMATIC_DECISION_MAX_AGE_SECONDS, checked_at):
            continue
        candidates.append(
            (
                _utc_now(created_at).timestamp(),
                confidence,
                str(row.symbol).strip().upper(),
                side,
                timeframe,
            )
        )
    return candidates


def _legacy_signal_candidates(signals, checked_at):
    """Compatibility fallback for installations not yet producing snapshots."""

    candidates = []
    for row in signals:
        timeframe = str(getattr(row, "timeframe", "") or "").strip().lower()
        side = _signal_side(getattr(row, "signal", None))
        confidence = _number(getattr(row, "confidence", None))
        created_at = getattr(row, "created_at", None)
        if timeframe not in PHASE2_OFFICIAL_TIMEFRAMES or side is None:
            continue
        if confidence is None or confidence < AUTOMATIC_MIN_CONFIDENCE:
            continue
        if not _is_fresh(created_at, timeframe, checked_at):
            continue
        candidates.append(
            (
                _utc_now(created_at).timestamp(),
                confidence,
                str(row.symbol).strip().upper(),
                side,
                timeframe,
            )
        )
    return candidates


def _snapshot_side(snapshot):
    try:
        payload = json.loads(getattr(snapshot, "snapshot_json", "") or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    context = payload.get("context") or {}
    signal = payload.get("signal") or {}
    return _signal_side(context.get("side") or signal.get("side"))


def _automatic_parameters(symbol, timeframe, side):
    defaults = phase2_walk_forward_defaults(timeframe)
    limit = min(
        20_000,
        minimum_candles_for_folds(
            defaults["train_size"],
            defaults["test_size"],
            defaults["step_size"],
            PHASE2_WALK_FORWARD_DAYS["minimum_folds"],
        ),
    )
    return {
        "symbol": str(symbol).strip().upper(),
        "timeframe": timeframe,
        "signal": side,
        "limit": limit,
        "stop_grid": [0.75, 1.0, 1.25, 1.5],
        "target_grid": [1.5, 2.0, 2.5, 3.0],
        "train_size": defaults["train_size"],
        "test_size": defaults["test_size"],
        "step_size": defaults["step_size"],
        "mode": "EXPANDING",
        "min_train_trades": 1,
        "initial_capital": 10_000,
        "position_size_percent": 100,
        "fee_bps": DEFAULT_FEE_BPS,
        "slippage_bps": 2,
        "strategy": "SIGNAL_GATED",
        "risk_percent_per_trade": None,
        "target_trade_volatility_percent": None,
        "max_leverage": 1,
        "max_open_positions": 20,
        "max_gross_exposure_percent": 500,
        "initial_portfolio_positions": [],
        "collision_policy": "STOP_FIRST",
    }


def _signal_side(value):
    normalized = str(value or "").strip().upper()
    if normalized in {"BUY", "LONG", "STRONG_LONG", "BULLISH"}:
        return "LONG"
    if normalized in {"SELL", "SHORT", "STRONG_SHORT", "BEARISH"}:
        return "SHORT"
    return None


def _is_fresh(created_at, timeframe, now):
    if created_at is None:
        return False
    age_seconds = max(0.0, (now - _utc_now(created_at)).total_seconds())
    return age_seconds <= (TIMEFRAME_SECONDS[timeframe] * 2 + 10 * 60)


def _is_recent(created_at, max_age_seconds, now):
    if created_at is None:
        return False
    age_seconds = max(0.0, (now - _utc_now(created_at)).total_seconds())
    return age_seconds <= max_age_seconds


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _utc_now(value=None):
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        return current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)
