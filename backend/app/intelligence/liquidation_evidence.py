"""Observed forced-order pressure, independent of historical price clusters."""
import math
from datetime import datetime, timedelta, timezone
from sqlalchemy import func
from app.database.models.liquidations import Liquidation
from app.utils.freshness import freshness_status, normalize_timestamp_to_naive_utc

LIQUIDATION_WINDOW_SECONDS = 4 * 60 * 60
LIQUIDATION_MAX_AGE_SECONDS = 30 * 60
ORDER_SIDE_METHOD = "ORDER_SIDE_V1"


def observed_liquidation_evidence(db, symbol, *, as_of_timestamp=None):
    as_of = normalize_timestamp_to_naive_utc(as_of_timestamp or datetime.now(timezone.utc))
    start = as_of - timedelta(seconds=LIQUIDATION_WINDOW_SECONDS)
    side = func.upper(Liquidation.side)
    rows = (
        db.query(side, func.sum(Liquidation.value_usd), func.count(Liquidation.id), func.max(Liquidation.event_time))
        .filter(Liquidation.symbol == symbol, Liquidation.venue == "BINANCE",
                Liquidation.event_time >= start, Liquidation.event_time <= as_of,
                Liquidation.value_usd > 0, Liquidation.price > 0, side.in_(["BUY", "SELL"]))
        .group_by(side).all()
    )
    totals = {"BUY": 0.0, "SELL": 0.0}
    count, latest = 0, None
    for order_side, value, events, timestamp in rows:
        value = float(value or 0)
        if not math.isfinite(value) or value <= 0:
            continue
        totals[order_side] += value
        count += int(events)
        if timestamp is not None and (latest is None or timestamp > latest):
            latest = timestamp
    # Forced SELL closes a long; forced BUY closes a short.
    longs, shorts = totals["SELL"], totals["BUY"]
    total = longs + shorts
    freshness = freshness_status(latest, LIQUIDATION_MAX_AGE_SECONDS, reference_timestamp=as_of)
    observed = total > 0 and not freshness["is_stale"]
    score = round(100 * (shorts - longs) / total, 4) if observed else None
    bias = ("SHORT_LIQUIDATIONS" if score > 0 else "LONG_LIQUIDATIONS" if score < 0 else "NEUTRAL") if observed else "UNAVAILABLE"
    return {
        "status": "READY" if observed else "STALE" if total else "UNAVAILABLE",
        "data_quality": "OBSERVED" if observed else "STALE" if total else "MISSING",
        "direction_method": ORDER_SIDE_METHOD, "bias": bias, "imbalance_score": score,
        "confidence": abs(score) if score is not None else 0,
        "long_liquidation_usd": longs, "short_liquidation_usd": shorts,
        "total_liquidation_usd": total, "source_event_count": count,
        "source_window_start": start, "source_window_end": as_of,
        "window_seconds": LIQUIDATION_WINDOW_SECONDS,
        "source_timestamp": latest, "freshness": freshness,
        "reason": ("Observed forced-buy pressure (short liquidations)" if score is not None and score > 0
                   else "Observed forced-sell pressure (long liquidations)" if score is not None and score < 0
                   else "Observed liquidation values are balanced" if observed
                   else "Latest observed liquidation event is stale" if total
                   else "No valid liquidation events in the observation window"),
        "coverage_note": "Binance sampled liquidation snapshots; not complete market-wide liquidation totals.",
    }


def liquidation_pressure_score(evidence, maximum=8):
    evidence = evidence or {}
    if evidence.get("data_quality") != "OBSERVED" or evidence.get("direction_method") != ORDER_SIDE_METHOD:
        return 0.0
    if (evidence.get("freshness") or {}).get("is_stale") is True:
        return 0.0
    try:
        score = float(evidence["imbalance_score"])
    except (KeyError, TypeError, ValueError):
        return 0.0
    return round(max(-100, min(100, score)) * maximum / 100, 4) if math.isfinite(score) else 0.0
