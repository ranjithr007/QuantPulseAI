from datetime import datetime
from datetime import timezone
from types import SimpleNamespace

from app.market_data.incremental_fetch import plan_incremental_fetch


NOW = datetime(2026, 7, 27, 10, 30, tzinfo=timezone.utc)


def test_bootstrap_fetch_is_small_and_boundary_bounded():
    plan = plan_incremental_fetch(None, "1h", now=NOW)

    assert plan.should_fetch is True
    assert plan.start_time_ms is None
    assert plan.limit == 3
    assert plan.reason == "BOOTSTRAP_RECENT"
    assert plan.current_open_time_ms == _ms(10)


def test_forming_candle_is_reloaded_from_its_open_boundary():
    latest = _cursor(10, is_final=False)

    plan = plan_incremental_fetch(latest, "1h", now=NOW)

    assert plan.should_fetch is True
    assert plan.start_time_ms == _ms(10)
    assert plan.limit == 1
    assert plan.reason == "REFRESH_FORMING"


def test_final_cursor_fetches_only_missing_boundaries_and_current_candle():
    latest = _cursor(6, is_final=True)

    plan = plan_incremental_fetch(latest, "1h", now=NOW)

    assert plan.start_time_ms == _ms(7)
    assert plan.limit == 4
    assert plan.reason == "CATCH_UP_BOUNDARIES"


def test_future_next_boundary_is_not_due():
    latest = _cursor(10, is_final=True)

    plan = plan_incremental_fetch(latest, "1h", now=NOW)

    assert plan.should_fetch is False
    assert plan.limit == 0
    assert plan.reason == "UP_TO_DATE"


def _cursor(hour, *, is_final):
    return SimpleNamespace(
        open_time=datetime(
            2026,
            7,
            27,
            hour,
            tzinfo=timezone.utc,
        ),
        is_final=is_final,
    )


def _ms(hour):
    return int(
        datetime(
            2026,
            7,
            27,
            hour,
            tzinfo=timezone.utc,
        ).timestamp()
        * 1000
    )
