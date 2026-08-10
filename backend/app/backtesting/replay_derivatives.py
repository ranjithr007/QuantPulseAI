"""Point-in-time futures derivatives context for historical replay."""

from datetime import timezone

from app.utils.freshness import normalize_timestamp_to_utc


def build_derivatives_as_of(
    funding_records,
    open_interest_records,
    as_of_timestamp,
    *,
    mark_price_records=None,
    margin_bracket_records=None,
    funding_stale_after_seconds=43_200,
    open_interest_stale_after_seconds=7_200,
    mark_price_stale_after_seconds=7_200,
):
    cutoff = _aware_utc(as_of_timestamp)
    funding = _records_as_of(
        funding_records,
        cutoff,
        timestamp_names=("funding_time", "time"),
    )
    open_interest = _records_as_of(
        open_interest_records,
        cutoff,
        timestamp_names=("timestamp", "time"),
    )
    mark_prices = _records_as_of(
        mark_price_records,
        cutoff,
        timestamp_names=("close_time", "timestamp", "time"),
    )

    latest_funding = funding[-1] if funding else None
    latest_oi = open_interest[-1] if open_interest else None
    previous_oi = open_interest[-2] if len(open_interest) > 1 else None
    latest_mark = mark_prices[-1] if mark_prices else None
    funding_age = _age_seconds(
        cutoff,
        _timestamp(latest_funding, ("funding_time", "time")),
    )
    oi_age = _age_seconds(
        cutoff,
        _timestamp(latest_oi, ("timestamp", "time")),
    )
    mark_age = _age_seconds(
        cutoff,
        _timestamp(latest_mark, ("close_time", "timestamp", "time")),
    )
    funding_available = latest_funding is not None
    oi_available = latest_oi is not None
    mark_available = latest_mark is not None
    margin_brackets = _margin_brackets_as_of(margin_bracket_records, cutoff)

    return {
        "source": "point_in_time_replay_derivatives",
        "as_of": cutoff,
        "status": (
            "READY"
            if funding_available and oi_available
            else "PARTIAL"
            if funding_available or oi_available
            else "NO_DATA"
        ),
        "availability": {
            "funding": funding_available,
            "open_interest": oi_available,
            "mark_price": mark_available,
            "margin_brackets": bool(margin_brackets),
        },
        "funding": {
            "rate": _number(latest_funding, ("rate",)),
            "timestamp": _timestamp(latest_funding, ("funding_time", "time")),
            "age_seconds": funding_age,
            "freshness": _freshness(funding_age, funding_stale_after_seconds),
        },
        "open_interest": {
            "value": _number(latest_oi, ("value",)),
            "timestamp": _timestamp(latest_oi, ("timestamp", "time")),
            "age_seconds": oi_age,
            "freshness": _freshness(oi_age, open_interest_stale_after_seconds),
            "change_pct": _change_pct(
                _number(previous_oi, ("value",)),
                _number(latest_oi, ("value",)),
            ),
        },
        "mark_price": {
            "open": _number(latest_mark, ("open_price", "open")),
            "high": _number(latest_mark, ("high_price", "high")),
            "low": _number(latest_mark, ("low_price", "low")),
            "close": _number(latest_mark, ("close_price", "close", "mark_price")),
            "timestamp": _timestamp(
                latest_mark,
                ("close_time", "timestamp", "time"),
            ),
            "age_seconds": mark_age,
            "freshness": _freshness(mark_age, mark_price_stale_after_seconds),
            "source": (
                latest_mark.get("source")
                if isinstance(latest_mark, dict)
                else getattr(latest_mark, "source", None)
            ),
        },
        "margin_brackets": {
            "available": bool(margin_brackets),
            "snapshot_version": (
                margin_brackets[0]["snapshot_version"]
                if margin_brackets
                else None
            ),
            "effective_at": (
                margin_brackets[0]["effective_at"]
                if margin_brackets
                else None
            ),
            "brackets": margin_brackets,
        },
        "leakage_status": "PASS",
    }


def _records_as_of(records, cutoff, *, timestamp_names):
    if cutoff is None:
        return []
    eligible = []
    for record in records or []:
        event_time = _timestamp(record, timestamp_names)
        if event_time is not None and event_time <= cutoff:
            eligible.append((event_time, record))
    eligible.sort(key=lambda item: item[0])
    return [record for _, record in eligible]


def _timestamp(record, names):
    if record is None:
        return None
    for name in names:
        value = record.get(name) if isinstance(record, dict) else getattr(record, name, None)
        normalized = _aware_utc(value)
        if normalized is not None:
            return normalized
    return None


def _number(record, names):
    if record is None:
        return None
    for name in names:
        value = record.get(name) if isinstance(record, dict) else getattr(record, name, None)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                return None
    return None


def _aware_utc(value):
    normalized = normalize_timestamp_to_utc(value)
    if normalized is None:
        return None
    if normalized.tzinfo is None:
        return normalized.replace(tzinfo=timezone.utc)
    return normalized.astimezone(timezone.utc)


def _age_seconds(cutoff, event_time):
    if cutoff is None or event_time is None:
        return None
    return round(max(0.0, (cutoff - event_time).total_seconds()), 3)


def _freshness(age_seconds, stale_after_seconds):
    if age_seconds is None:
        return "UNAVAILABLE"
    return "FRESH" if age_seconds <= stale_after_seconds else "STALE"


def _change_pct(previous, current):
    if previous in (None, 0) or current is None:
        return None
    return round(((current - previous) / previous) * 100, 4)


def _margin_brackets_as_of(records, cutoff):
    eligible = _records_as_of(
        records,
        cutoff,
        timestamp_names=("effective_at",),
    )
    if not eligible:
        return []
    latest = eligible[-1]
    version = (
        latest.get("snapshot_version")
        if isinstance(latest, dict)
        else getattr(latest, "snapshot_version", None)
    )
    selected = []
    for item in eligible:
        item_version = (
            item.get("snapshot_version")
            if isinstance(item, dict)
            else getattr(item, "snapshot_version", None)
        )
        if item_version != version:
            continue
        selected.append(
            {
                "bracket": int(_number(item, ("bracket_number", "bracket"))),
                "notional_floor": _number(item, ("notional_floor", "notionalFloor")),
                "notional_cap": _number(item, ("notional_cap", "notionalCap")),
                "max_leverage": _number(item, ("initial_leverage", "initialLeverage")),
                "maintenance_margin_rate": _number(
                    item,
                    ("maintenance_margin_rate", "maintMarginRatio"),
                ),
                "maintenance_amount": _number(
                    item,
                    ("maintenance_amount", "cum"),
                )
                or 0.0,
                "snapshot_version": version,
                "effective_at": _timestamp(item, ("effective_at",)),
                "source": (
                    item.get("source")
                    if isinstance(item, dict)
                    else getattr(item, "source", None)
                ),
            }
        )
    return sorted(selected, key=lambda item: item["notional_floor"])
