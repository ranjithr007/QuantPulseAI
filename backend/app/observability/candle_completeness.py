"""Read-only candle continuity and temporal-validation progress reporting."""

from datetime import datetime, timezone

from app.market_data.quality import analyze_candle_sequence
from app.market_data.quality import assess_window_coverage
from app.repositories.candle_repository import get_candles_as_of
from app.utils.freshness import normalize_timestamp_to_utc
from app.utils.timeframes import timeframe_seconds


VALIDATION_SYMBOLS = ("BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT", "BNBUSDT")
VALIDATION_TIMEFRAMES = ("1h", "4h", "1d")
INSPECTED_CUTOFF = datetime(2026, 7, 27, 15, tzinfo=timezone.utc)
TARGET_UNTOUCHED_1H_CANDLES = 1440
_LAST_REPORT = None


def build_candle_completeness_report(
    db,
    *,
    symbols=VALIDATION_SYMBOLS,
    timeframes=VALIDATION_TIMEFRAMES,
    now=None,
    candle_loader=get_candles_as_of,
):
    observed_at = normalize_timestamp_to_utc(now or datetime.now(timezone.utc))
    start_ms = int(INSPECTED_CUTOFF.timestamp() * 1000) + 1
    end_ms = int(observed_at.timestamp() * 1000)
    series = {}
    unhealthy = []

    for symbol in symbols:
        for timeframe in timeframes:
            interval_seconds = timeframe_seconds(timeframe)
            expected_since_cutoff = max(
                int((end_ms - start_ms) // (interval_seconds * 1000)),
                0,
            )
            limit = max(expected_since_cutoff + 32, 200)
            candles = list(
                candle_loader(
                    db,
                    symbol,
                    timeframe,
                    observed_at,
                    limit=limit,
                )
                or []
            )
            post_cutoff = [
                candle
                for candle in candles
                if (
                    (_open_timestamp(candle) is not None)
                    and _open_timestamp(candle) > INSPECTED_CUTOFF
                )
            ]
            sequence = analyze_candle_sequence(post_cutoff, timeframe)
            coverage = assess_window_coverage(
                post_cutoff,
                timeframe,
                start_time_ms=start_ms,
                end_time_ms=end_ms,
            )
            latest_open = (
                max(
                    (_open_timestamp(candle) for candle in post_cutoff),
                    default=None,
                )
                if post_cutoff
                else None
            )
            latest_close = (
                latest_open
                + _seconds(interval_seconds)
                if latest_open is not None
                else None
            )
            age_seconds = (
                max((observed_at - latest_close).total_seconds(), 0)
                if latest_close is not None
                else None
            )
            stale = (
                age_seconds is None
                or age_seconds > interval_seconds * 2
            )
            issues = list(sequence["issues"])
            if coverage["missing_count"]:
                issues.append("WINDOW_GAPS")
            if stale:
                issues.append("STALE_LATEST_FINAL_CANDLE")
            issues = sorted(set(issues))
            key = f"{symbol}:{timeframe}"
            series[key] = {
                "symbol": symbol,
                "timeframe": timeframe,
                "status": "HEALTHY" if not issues else "DEGRADED",
                "observed_after_cutoff": len(post_cutoff),
                "expected_after_cutoff": coverage["expected_count"],
                "missing_after_cutoff": coverage["missing_count"],
                "missing_open_time_sample": coverage[
                    "missing_open_time_sample"
                ],
                "latest_open_time": _iso(latest_open),
                "latest_close_time": _iso(latest_close),
                "latest_age_seconds": (
                    round(age_seconds, 2) if age_seconds is not None else None
                ),
                "issues": issues,
                "sequence": {
                    "duplicate_count": len(sequence["duplicate_open_times"]),
                    "out_of_order_count": len(sequence["out_of_order"]),
                    "internal_gap_count": sequence["missing_candle_count"],
                    "provisional_count": len(sequence["provisional_indexes"]),
                },
            }
            if issues:
                unhealthy.append(key)

    hourly = [
        value
        for value in series.values()
        if value["timeframe"] == "1h"
    ]
    completed_by_symbol = {
        item["symbol"]: min(
            item["observed_after_cutoff"],
            TARGET_UNTOUCHED_1H_CANDLES,
        )
        for item in hourly
    }
    safe_completed = min(completed_by_symbol.values(), default=0)
    temporal_ready = bool(hourly) and all(
        item["observed_after_cutoff"] >= TARGET_UNTOUCHED_1H_CANDLES
        and item["missing_after_cutoff"] == 0
        and "STALE_LATEST_FINAL_CANDLE" not in item["issues"]
        for item in hourly
    )
    return {
        "contract": "candle_completeness_monitor_v1",
        "status": "HEALTHY" if not unhealthy else "DEGRADED",
        "source": "canonical_final_candle_repository",
        "read_only": True,
        "observed_at": observed_at.isoformat(),
        "inspected_cutoff": INSPECTED_CUTOFF.isoformat(),
        "symbols": list(symbols),
        "timeframes": list(timeframes),
        "unhealthy_series": unhealthy,
        "series": series,
        "temporal_validation": {
            "ready": temporal_ready,
            "target_1h_candles_per_symbol": TARGET_UNTOUCHED_1H_CANDLES,
            "completed_1h_candles_by_symbol": completed_by_symbol,
            "safe_completed_1h_candles": safe_completed,
            "remaining_1h_candles": max(
                TARGET_UNTOUCHED_1H_CANDLES - safe_completed,
                0,
            ),
            "progress_percent": round(
                min(
                    safe_completed / TARGET_UNTOUCHED_1H_CANDLES * 100,
                    100,
                ),
                2,
            ),
            "readiness_policy": (
                "ALL_SYMBOLS_COMPLETE_WITH_NO_POST_CUTOFF_GAPS"
            ),
        },
    }


def cache_candle_completeness_report(report):
    global _LAST_REPORT
    _LAST_REPORT = report
    return report


def get_cached_candle_completeness_report():
    return _LAST_REPORT


def _open_timestamp(candle):
    value = (
        candle.get("open_time")
        if isinstance(candle, dict)
        else getattr(candle, "open_time", None)
    )
    if value is None:
        value = (
            candle.get("candle_time")
            if isinstance(candle, dict)
            else getattr(candle, "candle_time", None)
        )
    return normalize_timestamp_to_utc(value)


def _seconds(value):
    from datetime import timedelta

    return timedelta(seconds=value)


def _iso(value):
    return value.isoformat() if value is not None else None
