from datetime import datetime
from datetime import timezone


DEFAULT_STALE_AFTER_SECONDS = 15 * 60
TIMEFRAME_STALE_AFTER_SECONDS = {
    "1m": 5 * 60,
    "5m": 15 * 60,
    "15m": 25 * 60,
    "1h": 65 * 60,
    "2h": (2 * 60 + 5) * 60,
    "4h": (4 * 60 + 5) * 60,
    "1d": (24 * 60 + 25) * 60,
}


def stale_after_seconds_for_timeframe(timeframe, fallback=DEFAULT_STALE_AFTER_SECONDS):
    if not timeframe:
        return fallback

    return TIMEFRAME_STALE_AFTER_SECONDS.get(str(timeframe).lower(), fallback)


def freshness_status(
    timestamp,
    stale_after_seconds=DEFAULT_STALE_AFTER_SECONDS,
    *,
    reference_timestamp=None,
):
    if timestamp is None:
        return {
            "data_timestamp": None,
            "data_age_seconds": None,
            "is_future": False,
            "future_by_seconds": 0,
            "is_stale": True,
            "timezone_assumption": None,
            "stale_after_seconds": stale_after_seconds,
        }

    now = (
        normalize_timestamp_to_utc(reference_timestamp)
        if reference_timestamp is not None
        else datetime.now(timezone.utc)
    )
    normalized, timezone_assumption = _as_utc(timestamp, now)
    age_seconds = int((now - normalized).total_seconds())
    is_future = age_seconds < 0

    return {
        "data_timestamp": timestamp,
        "data_age_seconds": max(0, age_seconds),
        "is_future": is_future,
        "future_by_seconds": abs(age_seconds) if is_future else 0,
        "is_stale": is_future or age_seconds > stale_after_seconds,
        "timezone_assumption": timezone_assumption,
        "stale_after_seconds": stale_after_seconds,
    }


def candle_freshness_timestamp(candle):
    """Use the close boundary when measuring a candle's age."""
    if candle is None:
        return None

    if isinstance(candle, dict):
        return (
            candle.get("close_time")
            or candle.get("candle_time")
            or candle.get("open_time")
        )

    return (
        getattr(candle, "close_time", None)
        or getattr(candle, "candle_time", None)
        or getattr(candle, "open_time", None)
    )


def orm_to_dict(record):
    if record is None:
        return None

    return {
        column.name: getattr(record, column.name)
        for column in record.__table__.columns
    }


def with_freshness(record, timestamp_attr, stale_after_seconds=DEFAULT_STALE_AFTER_SECONDS):
    data = orm_to_dict(record)

    if data is None:
        return None

    data["freshness"] = freshness_status(
        getattr(record, timestamp_attr, None),
        stale_after_seconds,
    )

    return data


def normalize_timestamp_to_utc(timestamp):
    if timestamp is None:
        return None

    normalized, _timezone_assumption = _as_utc(timestamp)
    return normalized


def _as_utc(timestamp, now=None):
    if timestamp.tzinfo is None:
        now = now or datetime.now(timezone.utc)
        utc_candidate = timestamp.replace(tzinfo=timezone.utc)
        age_seconds = int((now - utc_candidate).total_seconds())

        if age_seconds < -(30 * 60):
            local_tz = datetime.now().astimezone().tzinfo
            local_candidate = timestamp.replace(tzinfo=local_tz).astimezone(timezone.utc)

            if local_candidate <= now:
                return local_candidate, "local_naive"

        return utc_candidate, "utc_naive"

    return timestamp.astimezone(timezone.utc), "aware"
