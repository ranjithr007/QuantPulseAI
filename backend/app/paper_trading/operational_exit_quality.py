"""Shared classification for exits whose result was distorted by monitor delay."""

from datetime import datetime, timedelta

from app.paper_trading.exit_evidence import read_evidence


EXIT_DEADLINE_GRACE_MINUTES = 10
MAX_PROMOTION_EXIT_QUOTE_AGE_SECONDS = 5.0
RECORDED_EXIT_CLASSIFICATIONS = {
    "INITIAL_STOP",
    "TRAILED_STOP_PRE_T1",
    "PROTECTED_STOP_AFTER_T1",
    "TARGET",
    "TARGET1",
    "TARGET2",
    "TIME_EXIT",
}
RECORDED_EXIT_EVIDENCE_KINDS = {"LIVE_MARK", "CANDLE_OHLC"}


def late_time_exit_delay_minutes(trade, grace_minutes=EXIT_DEADLINE_GRACE_MINUTES):
    """Return the deadline breach for a contaminated time exit, otherwise None."""

    if str(_value(trade, "status") or "").upper() != "CLOSED":
        return None
    if str(_value(trade, "exit_reason") or "").upper() != "TIME_EXIT":
        return None
    opened_at = _as_datetime(_value(trade, "opened_at"))
    closed_at = _as_datetime(_value(trade, "closed_at"))
    if opened_at is None or closed_at is None:
        return None
    try:
        max_hold_hours = float(_value(trade, "max_hold_hours"))
    except (TypeError, ValueError):
        return None
    if max_hold_hours <= 0:
        return None
    delay_minutes = (
        closed_at - (opened_at + timedelta(hours=max_hold_hours))
    ).total_seconds() / 60
    return delay_minutes if delay_minutes > float(grace_minutes) else None


def is_operationally_contaminated_exit(trade, grace_minutes=EXIT_DEADLINE_GRACE_MINUTES):
    return (
        late_time_exit_delay_minutes(trade, grace_minutes) is not None
        or stale_recorded_exit_quote_age_seconds(trade) is not None
    )


def recorded_exit_evidence_quality(trade):
    evidence = read_evidence(_value(trade, "exit_evidence_json"))
    classification = str(evidence.get("classification") or "").upper()
    evidence_kind = str(evidence.get("evidence_kind") or "").upper()
    recorded = (
        classification in RECORDED_EXIT_CLASSIFICATIONS
        and evidence_kind in RECORDED_EXIT_EVIDENCE_KINDS
        and bool(evidence.get("observed_at"))
    )
    quote_age_seconds = _finite_number(evidence.get("quote_age_seconds"))
    timely = (
        recorded
        and quote_age_seconds is not None
        and 0 <= quote_age_seconds <= MAX_PROMOTION_EXIT_QUOTE_AGE_SECONDS
    )
    return {
        "recorded": recorded,
        "timely": timely,
        "quote_age_seconds": quote_age_seconds,
    }


def stale_recorded_exit_quote_age_seconds(trade):
    quality = recorded_exit_evidence_quality(trade)
    if not quality["recorded"] or quality["quote_age_seconds"] is None:
        return None
    return (
        quality["quote_age_seconds"]
        if quality["quote_age_seconds"] > MAX_PROMOTION_EXIT_QUOTE_AGE_SECONDS
        else None
    )


def _value(item, name):
    if isinstance(item, dict):
        return item.get(name)
    return getattr(item, name, None)


def _as_datetime(value):
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo is not None else value
    if value is None:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(
            tzinfo=None
        )
    except (TypeError, ValueError):
        return None


def _finite_number(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and result not in (float("inf"), float("-inf")) else None
