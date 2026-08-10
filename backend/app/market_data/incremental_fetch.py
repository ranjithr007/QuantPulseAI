from dataclasses import asdict
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone

from app.utils.freshness import normalize_timestamp_to_utc
from app.utils.timeframes import timeframe_seconds


DEFAULT_BOOTSTRAP_LIMIT = 3
MAX_INCREMENTAL_CANDLES = 1500


@dataclass(frozen=True)
class IncrementalFetchPlan:
    timeframe: str
    should_fetch: bool
    start_time_ms: int | None
    end_time_ms: int
    limit: int
    reason: str
    latest_open_time_ms: int | None
    latest_is_final: bool | None
    current_open_time_ms: int

    def as_dict(self):
        return asdict(self)


def plan_incremental_fetch(
    latest_candle,
    timeframe,
    *,
    now=None,
    bootstrap_limit=DEFAULT_BOOTSTRAP_LIMIT,
    maximum_limit=MAX_INCREMENTAL_CANDLES,
):
    interval_ms = timeframe_seconds(timeframe) * 1000
    now_utc = normalize_timestamp_to_utc(now or datetime.now(timezone.utc))
    now_ms = int(now_utc.timestamp() * 1000)
    current_open_time_ms = (now_ms // interval_ms) * interval_ms
    end_time_ms = now_ms

    if latest_candle is None:
        return IncrementalFetchPlan(
            timeframe=timeframe,
            should_fetch=True,
            start_time_ms=None,
            end_time_ms=end_time_ms,
            limit=max(1, min(int(bootstrap_limit), int(maximum_limit))),
            reason="BOOTSTRAP_RECENT",
            latest_open_time_ms=None,
            latest_is_final=None,
            current_open_time_ms=current_open_time_ms,
        )

    latest_open_time_ms = _timestamp_ms(
        getattr(latest_candle, "open_time", None)
        or getattr(latest_candle, "candle_time", None)
    )
    if latest_open_time_ms is None:
        return IncrementalFetchPlan(
            timeframe=timeframe,
            should_fetch=True,
            start_time_ms=None,
            end_time_ms=end_time_ms,
            limit=max(1, min(int(bootstrap_limit), int(maximum_limit))),
            reason="CURSOR_INVALID_BOOTSTRAP",
            latest_open_time_ms=None,
            latest_is_final=bool(getattr(latest_candle, "is_final", False)),
            current_open_time_ms=current_open_time_ms,
        )

    latest_is_final = bool(getattr(latest_candle, "is_final", False))
    start_time_ms = (
        latest_open_time_ms + interval_ms
        if latest_is_final
        else latest_open_time_ms
    )
    if start_time_ms > current_open_time_ms:
        return IncrementalFetchPlan(
            timeframe=timeframe,
            should_fetch=False,
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
            limit=0,
            reason="UP_TO_DATE",
            latest_open_time_ms=latest_open_time_ms,
            latest_is_final=latest_is_final,
            current_open_time_ms=current_open_time_ms,
        )

    expected_count = (
        (current_open_time_ms - start_time_ms) // interval_ms
    ) + 1
    return IncrementalFetchPlan(
        timeframe=timeframe,
        should_fetch=True,
        start_time_ms=start_time_ms,
        end_time_ms=end_time_ms,
        limit=max(1, min(int(expected_count), int(maximum_limit))),
        reason=(
            "REFRESH_FORMING"
            if not latest_is_final and expected_count == 1
            else "CATCH_UP_BOUNDARIES"
        ),
        latest_open_time_ms=latest_open_time_ms,
        latest_is_final=latest_is_final,
        current_open_time_ms=current_open_time_ms,
    )


def _timestamp_ms(value):
    normalized = normalize_timestamp_to_utc(value)
    if normalized is None:
        return None
    return int(normalized.timestamp() * 1000)
