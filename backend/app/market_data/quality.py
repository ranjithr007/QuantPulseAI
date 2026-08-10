from collections import Counter

from app.utils.freshness import normalize_timestamp_to_utc
from app.utils.timeframes import timeframe_seconds


def analyze_candle_sequence(
    candles,
    timeframe,
    *,
    allow_trailing_provisional=False,
):
    interval_ms = timeframe_seconds(timeframe) * 1000
    records = list(candles or [])
    open_times = [_open_time_ms(candle) for candle in records]
    valid_times = [value for value in open_times if value is not None]

    counts = Counter(valid_times)
    duplicate_times = sorted(
        value for value, count in counts.items() if count > 1
    )
    out_of_order = [
        {
            "index": index,
            "previous_open_time_ms": valid_times[index - 1],
            "open_time_ms": valid_times[index],
        }
        for index in range(1, len(valid_times))
        if valid_times[index] <= valid_times[index - 1]
    ]

    gaps = []
    for previous, current in zip(
        sorted(set(valid_times)),
        sorted(set(valid_times))[1:],
    ):
        delta = current - previous
        if delta > interval_ms:
            missing_count = (delta // interval_ms) - 1
            gaps.append(
                {
                    "after_open_time_ms": previous,
                    "before_open_time_ms": current,
                    "missing_count": int(missing_count),
                    "first_missing_open_time_ms": previous + interval_ms,
                    "last_missing_open_time_ms": current - interval_ms,
                }
            )

    provisional_indexes = [
        index
        for index, candle in enumerate(records)
        if _value(candle, "is_final") is False
    ]
    if (
        allow_trailing_provisional
        and provisional_indexes == [len(records) - 1]
    ):
        provisional_indexes = []
    missing_time_indexes = [
        index for index, value in enumerate(open_times) if value is None
    ]
    issues = []
    if duplicate_times:
        issues.append("DUPLICATE_OPEN_TIMES")
    if out_of_order:
        issues.append("OUT_OF_ORDER")
    if gaps:
        issues.append("GAPS")
    if provisional_indexes:
        issues.append("PROVISIONAL_ROWS")
    if missing_time_indexes:
        issues.append("MISSING_OPEN_TIME")

    return {
        "status": "PASS" if not issues else "FAIL",
        "timeframe": timeframe,
        "row_count": len(records),
        "first_open_time_ms": min(valid_times) if valid_times else None,
        "last_open_time_ms": max(valid_times) if valid_times else None,
        "duplicate_open_times": duplicate_times,
        "out_of_order": out_of_order,
        "gaps": gaps,
        "missing_candle_count": sum(
            item["missing_count"] for item in gaps
        ),
        "provisional_indexes": provisional_indexes,
        "missing_time_indexes": missing_time_indexes,
        "issues": issues,
    }


def compare_candle_sources(
    primary_candles,
    secondary_candles,
    *,
    price_tolerance_bps=25.0,
    volume_tolerance_ratio=0.50,
    enforce_volume=False,
):
    primary = {
        _open_time_ms(candle): candle
        for candle in primary_candles or []
        if _open_time_ms(candle) is not None
    }
    secondary = {
        _open_time_ms(candle): candle
        for candle in secondary_candles or []
        if _open_time_ms(candle) is not None
    }
    overlapping = sorted(set(primary) & set(secondary))
    disagreements = []

    for open_time_ms in overlapping:
        left = primary[open_time_ms]
        right = secondary[open_time_ms]
        price_differences = {
            field: _relative_bps(
                _value(left, field),
                _value(right, field),
            )
            for field in ("open", "high", "low", "close")
        }
        left_volume = _value(left, "volume")
        right_volume = _value(right, "volume")
        volume_ratio = _relative_ratio(left_volume, right_volume)
        price_mismatch = any(
            value > float(price_tolerance_bps)
            for value in price_differences.values()
        )
        volume_mismatch = volume_ratio > float(volume_tolerance_ratio)
        if price_mismatch or volume_mismatch:
            disagreements.append(
                {
                    "open_time_ms": open_time_ms,
                    "price_difference_bps": price_differences,
                    "volume_difference_ratio": volume_ratio,
                    "price_mismatch": price_mismatch,
                    "volume_mismatch": volume_mismatch,
                }
            )

    price_disagreement_count = sum(
        1 for item in disagreements if item["price_mismatch"]
    )
    volume_difference_count = sum(
        1 for item in disagreements if item["volume_mismatch"]
    )
    if not overlapping:
        status = "INSUFFICIENT_OVERLAP"
    elif (
        price_disagreement_count == 0
        and (not enforce_volume or volume_difference_count == 0)
    ):
        status = "PASS"
    else:
        status = "REVIEW"

    return {
        "status": status,
        "primary_count": len(primary),
        "secondary_count": len(secondary),
        "overlap_count": len(overlapping),
        "primary_only_count": len(set(primary) - set(secondary)),
        "secondary_only_count": len(set(secondary) - set(primary)),
        "disagreement_count": len(disagreements),
        "price_disagreement_count": price_disagreement_count,
        "volume_context_difference_count": volume_difference_count,
        "price_tolerance_bps": float(price_tolerance_bps),
        "volume_tolerance_ratio": float(volume_tolerance_ratio),
        "volume_tolerance_enforced": bool(enforce_volume),
        "reason": (
            "No common final candle identities were returned by both sources."
            if not overlapping
            else None
        ),
        "disagreements": disagreements,
    }


def assess_window_coverage(
    candles,
    timeframe,
    *,
    start_time_ms,
    end_time_ms,
    missing_sample_limit=20,
):
    interval_ms = timeframe_seconds(timeframe) * 1000
    expected_first = (
        (int(start_time_ms) + interval_ms - 1) // interval_ms
    ) * interval_ms
    expected_last = (
        (int(end_time_ms) // interval_ms) * interval_ms
    ) - interval_ms
    if expected_last < expected_first:
        expected_count = 0
    else:
        expected_count = (
            (expected_last - expected_first) // interval_ms
        ) + 1

    observed = {
        value
        for value in (_open_time_ms(candle) for candle in candles or [])
        if (
            value is not None
            and expected_first <= value <= expected_last
            and (value - expected_first) % interval_ms == 0
        )
    }
    missing_count = max(int(expected_count) - len(observed), 0)
    missing_sample = []
    cursor = expected_first
    while (
        cursor <= expected_last
        and len(missing_sample) < int(missing_sample_limit)
    ):
        if cursor not in observed:
            missing_sample.append(cursor)
        cursor += interval_ms

    return {
        "status": "PASS" if missing_count == 0 else "FAIL",
        "timeframe": timeframe,
        "expected_first_open_time_ms": (
            expected_first if expected_count else None
        ),
        "expected_last_final_open_time_ms": (
            expected_last if expected_count else None
        ),
        "expected_count": int(expected_count),
        "observed_count": len(observed),
        "missing_count": missing_count,
        "missing_open_time_sample": missing_sample,
        "sample_truncated": missing_count > len(missing_sample),
    }


def _open_time_ms(candle):
    value = _value(candle, "open_time_ms")
    if value is not None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    timestamp = (
        _value(candle, "open_time")
        or _value(candle, "candle_time")
    )
    normalized = normalize_timestamp_to_utc(timestamp)
    if normalized is None:
        return None
    return int(normalized.timestamp() * 1000)


def _value(candle, name):
    if isinstance(candle, dict):
        if name in candle:
            return candle.get(name)
        aliases = {
            "open": "open_price",
            "high": "high_price",
            "low": "low_price",
            "close": "close_price",
        }
        return candle.get(aliases.get(name, name))
    value = getattr(candle, name, None)
    if value is not None:
        return value
    aliases = {
        "open": "open_price",
        "high": "high_price",
        "low": "low_price",
        "close": "close_price",
    }
    return getattr(candle, aliases.get(name, name), None)


def _relative_bps(left, right):
    left_value = float(left or 0)
    right_value = float(right or 0)
    denominator = max(abs(left_value), abs(right_value), 1e-12)
    return abs(left_value - right_value) / denominator * 10_000


def _relative_ratio(left, right):
    left_value = float(left or 0)
    right_value = float(right or 0)
    denominator = max(abs(left_value), abs(right_value), 1e-12)
    return abs(left_value - right_value) / denominator
