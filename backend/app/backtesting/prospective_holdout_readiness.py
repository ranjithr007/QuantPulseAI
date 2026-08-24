"""Outcome-blind data readiness for the prospective walk-forward holdout."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, inspect
from sqlalchemy.exc import SQLAlchemyError

from app.backtesting.prospective_holdout import DEFAULT_MANIFEST_PATH
from app.database.models.funding_rates import FundingRate
from app.database.models.futures_mark_prices import FuturesMarkPrice
from app.database.models.liquidations import Liquidation
from app.database.models.market_candles import MarketCandle
from app.database.models.open_interest import OpenInterest
from app.database.models.orderbook_snapshots import OrderBookSnapshot
from app.database.models.spot_market_candles import SpotMarketCandle
from app.database.models.whale_trades import WhaleTrade
from app.governance.evidence_policy import OFFICIAL_ENTRY_TIMEFRAMES


READINESS_VERSION = "prospective_holdout_data_readiness_v1"
DEFAULT_SYMBOLS = (
    "BTCUSDT",
    "ETHUSDT",
    "XRPUSDT",
    "SOLUSDT",
    "BNBUSDT",
    "DOGEUSDT",
)
TIMEFRAME_MINUTES = {"1h": 60, "2h": 120, "4h": 240, "1d": 1440}
MINIMUM_COVERAGE_PERCENT = 90.0


def collect_inventory(session, *, cutoff, symbols=DEFAULT_SYMBOLS):
    """Read counts and timestamps only; never construct signals or trades."""

    cutoff_naive = _utc(cutoff).replace(tzinfo=None)
    rows = []
    for dataset, model, timestamp_column, critical in (
        ("futures_candles", MarketCandle, MarketCandle.close_time, True),
        ("spot_candles", SpotMarketCandle, SpotMarketCandle.close_time, True),
        ("mark_prices", FuturesMarkPrice, FuturesMarkPrice.close_time, False),
    ):
        dataset_error = _table_error(session, model)
        for symbol in symbols:
            for timeframe in OFFICIAL_ENTRY_TIMEFRAMES:
                if dataset_error:
                    count, first_time, latest_time, query_error = (
                        0,
                        None,
                        None,
                        dataset_error,
                    )
                else:
                    query = session.query(
                        func.count(model.id),
                        func.min(timestamp_column),
                        func.max(timestamp_column),
                    ).filter(
                        model.symbol == symbol,
                        model.timeframe == timeframe,
                        timestamp_column > cutoff_naive,
                    )
                    if hasattr(model, "is_final"):
                        query = query.filter(model.is_final.is_(True))
                    count, first_time, latest_time, query_error = _query_inventory(
                        session, query
                    )
                    if query_error:
                        dataset_error = query_error
                cadence = TIMEFRAME_MINUTES[timeframe]
                rows.append(
                    _inventory_row(
                        dataset,
                        symbol,
                        count,
                        first_time,
                        latest_time,
                        timeframe=timeframe,
                        cadence_minutes=cadence,
                        freshness_minutes=max(15, cadence * 2),
                        critical=critical,
                        query_error=query_error,
                    )
                )

    event_specs = (
        ("funding_rates", FundingRate, FundingRate.funding_time, 480, 720, True, False),
        ("open_interest", OpenInterest, OpenInterest.timestamp, 2, 10, True, False),
        ("orderbook", OrderBookSnapshot, OrderBookSnapshot.event_time, 1, 10, False, False),
        ("liquidations", Liquidation, Liquidation.event_time, None, None, False, True),
        ("whale_trades", WhaleTrade, WhaleTrade.trade_time, None, None, False, True),
    )
    for dataset, model, timestamp_column, cadence, freshness, critical, event_driven in event_specs:
        dataset_error = _table_error(session, model)
        for symbol in symbols:
            if dataset_error:
                count, first_time, latest_time, query_error = (
                    0,
                    None,
                    None,
                    dataset_error,
                )
            else:
                query = session.query(
                    func.count(model.id),
                    func.min(timestamp_column),
                    func.max(timestamp_column),
                ).filter(
                    model.symbol == symbol,
                    timestamp_column > cutoff_naive,
                )
                count, first_time, latest_time, query_error = _query_inventory(
                    session, query
                )
                if query_error:
                    dataset_error = query_error
            rows.append(
                _inventory_row(
                    dataset,
                    symbol,
                    count,
                    first_time,
                    latest_time,
                    cadence_minutes=cadence,
                    freshness_minutes=freshness,
                    critical=critical,
                    event_driven=event_driven,
                    query_error=query_error,
                )
            )
    return rows


def assess_data_readiness(
    rows,
    *,
    cutoff,
    observed_at=None,
    minimum_calendar_days=7,
):
    observed = _utc(observed_at or datetime.now(timezone.utc))
    cutoff = _utc(cutoff)
    elapsed_minutes = max(0.0, (observed - cutoff).total_seconds() / 60)
    elapsed_days = elapsed_minutes / 1440
    scopes = []
    for source in rows:
        row = dict(source)
        count = int(row.get("records") or 0)
        cadence = _positive_number(row.get("cadence_minutes"))
        event_driven = bool(row.get("event_driven"))
        latest = _optional_utc(row.get("latest_time"))
        latest_age_minutes = (
            max(0.0, (observed - latest).total_seconds() / 60)
            if latest is not None
            else None
        )
        expected = math.floor(elapsed_minutes / cadence) if cadence else None
        coverage = (
            round(min(count / expected, 1.0) * 100, 2)
            if expected and expected > 0
            else None
        )
        freshness_limit = _positive_number(row.get("freshness_minutes"))

        if row.get("query_error"):
            status = "DATA_SOURCE_ERROR"
        elif event_driven:
            status = "OBSERVED" if count else "NO_EVENTS_OBSERVED"
        elif expected == 0:
            status = "COLLECTING"
        else:
            coverage_ok = coverage is not None and coverage >= MINIMUM_COVERAGE_PERCENT
            freshness_ok = (
                latest_age_minutes is not None
                and freshness_limit is not None
                and latest_age_minutes <= freshness_limit
            )
            status = "HEALTHY" if coverage_ok and freshness_ok else "GAP"
        scopes.append(
            {
                **row,
                "records": count,
                "expected_records": expected,
                "coverage_percent": coverage,
                "latest_age_minutes": (
                    round(latest_age_minutes, 2)
                    if latest_age_minutes is not None
                    else None
                ),
                "status": status,
            }
        )

    critical = [item for item in scopes if item.get("critical")]
    critical_gaps = [
        item
        for item in critical
        if item["status"] in {"GAP", "DATA_SOURCE_ERROR"}
    ]
    critical_collecting = [
        item for item in critical if item["status"] == "COLLECTING"
    ]
    window_open = elapsed_days >= float(minimum_calendar_days)
    if critical_gaps:
        status = "DATA_GAPS"
    elif window_open and not critical_collecting:
        status = "DATA_READY_FOR_WALK_FORWARD"
    else:
        status = "COLLECTING_DATA"
    return {
        "contract": READINESS_VERSION,
        "status": status,
        "outcome_data_accessed": False,
        "signals_constructed": False,
        "trades_constructed": False,
        "holdout_start_exclusive": cutoff.isoformat(),
        "observed_at": observed.isoformat(),
        "elapsed_calendar_days": round(elapsed_days, 4),
        "minimum_calendar_days": minimum_calendar_days,
        "days_remaining": round(max(0.0, minimum_calendar_days - elapsed_days), 4),
        "validation_window_open": window_open,
        "minimum_coverage_percent": MINIMUM_COVERAGE_PERCENT,
        "scope_count": len(scopes),
        "critical_scope_count": len(critical),
        "critical_gap_count": len(critical_gaps),
        "critical_collecting_count": len(critical_collecting),
        "scopes": scopes,
        "next_action": _next_action(status),
    }


def build_current_data_readiness(session, *, observed_at=None, manifest_path=None):
    manifest = json.loads(
        Path(manifest_path or DEFAULT_MANIFEST_PATH).read_text(encoding="utf-8")
    )
    cutoff = _utc(manifest["discovery_cutoff"])
    minimum_days = float(manifest["evidence_thresholds"]["minimum_calendar_days"])
    rows = collect_inventory(session, cutoff=cutoff)
    return assess_data_readiness(
        rows,
        cutoff=cutoff,
        observed_at=observed_at,
        minimum_calendar_days=minimum_days,
    )


def _inventory_row(
    dataset,
    symbol,
    records,
    first_time,
    latest_time,
    *,
    timeframe=None,
    cadence_minutes=None,
    freshness_minutes=None,
    critical=False,
    event_driven=False,
    query_error=None,
):
    return {
        "dataset": dataset,
        "symbol": symbol,
        "timeframe": timeframe,
        "records": int(records or 0),
        "first_time": _iso(first_time),
        "latest_time": _iso(latest_time),
        "cadence_minutes": cadence_minutes,
        "freshness_minutes": freshness_minutes,
        "critical": critical,
        "event_driven": event_driven,
        "query_error": query_error,
    }


def _query_inventory(session, query):
    try:
        count, first_time, latest_time = query.one()
        return count, first_time, latest_time, None
    except SQLAlchemyError as exc:
        session.rollback()
        original = getattr(exc, "orig", None)
        message = str(original or exc).splitlines()[0]
        return 0, None, None, f"{type(original or exc).__name__}: {message}"


def _table_error(session, model):
    try:
        exists = inspect(session.get_bind()).has_table(model.__tablename__)
    except SQLAlchemyError as exc:
        session.rollback()
        original = getattr(exc, "orig", None)
        message = str(original or exc).splitlines()[0]
        return f"{type(original or exc).__name__}: {message}"
    return None if exists else f"MissingTable: {model.__tablename__}"


def _next_action(status):
    if status == "DATA_GAPS":
        return "Repair critical collection gaps before running the prospective holdout."
    if status == "DATA_READY_FOR_WALK_FORWARD":
        return "Run the complete walk-forward once, then apply the frozen holdout evaluator."
    return "Continue collection; do not inspect or tune holdout outcomes yet."


def _utc(value):
    parsed = _optional_utc(value)
    if parsed is None:
        raise ValueError(f"Invalid required timestamp: {value!r}")
    return parsed


def _optional_utc(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value):
    parsed = _optional_utc(value)
    return parsed.isoformat() if parsed is not None else None


def _positive_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None
