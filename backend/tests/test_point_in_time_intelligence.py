from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.backtesting.point_in_time_intelligence import (
    build_candle_intelligence_as_of,
    build_stateful_intelligence_timeline,
    resolve_intelligence_timeline,
)
from app.backtesting.trade_simulator import _build_in_memory_stack_resolver
from app.backtesting.trade_simulator import _build_bounded_stack_history_resolver
from app.backtesting.trade_simulator import _stack_history_limit


def _candles(count=80):
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    items = []
    for index in range(count):
        opened = base + timedelta(hours=index)
        open_price = 100 + index * 0.25
        close_price = open_price + 0.2
        items.append(
            SimpleNamespace(
                candle_time=opened,
                open_time=opened,
                close_time=opened + timedelta(hours=1),
                is_final=True,
                open_price=open_price,
                high_price=close_price + 0.15,
                low_price=open_price - 0.15,
                close_price=close_price,
                volume=1_000 + index,
            )
        )
    return items


def test_candle_intelligence_reconstructs_governed_master_components_as_of():
    candles = _candles()
    cutoff = candles[-1].close_time

    result = build_candle_intelligence_as_of(
        "DOGEUSDT",
        "1h",
        candles,
        source_timestamp=cutoff,
        effective_timestamp=cutoff,
    )

    assert result["leakage_status"] == "PASS"
    assert result["effective_timestamp"].replace(tzinfo=timezone.utc) == cutoff
    assert result["signal"]["signal"] in {"LONG", "SHORT", "WAIT"}
    assert set(result["signal"]["scoring_profile"]["base_weights"]) == {
        "feature",
        "regime",
        "orderflow",
        "smc",
    }
    assert result["availability"]["derivatives"] == "NOT_SUPPLIED"
    assert result["availability"]["orderflow"] == "RECONSTRUCTED_INITIAL_WINDOW_CVD"


def test_stateful_timeline_reconstructs_hysteresis_and_persistent_cvd():
    candles = _candles(65)

    timeline = build_stateful_intelligence_timeline(
        "DOGEUSDT",
        "1h",
        candles,
    )

    assert len(timeline) == 16
    assert timeline[0]["intelligence"]["availability"]["regime"] == (
        "RECONSTRUCTED_INITIAL_STATE"
    )
    assert timeline[1]["intelligence"]["availability"]["regime"] == (
        "RECONSTRUCTED_WITH_HYSTERESIS_STATE"
    )
    assert timeline[1]["intelligence"]["availability"]["orderflow"] == (
        "RECONSTRUCTED_PERSISTENT_CVD"
    )
    assert timeline[-1]["effective_timestamp"] > timeline[0]["effective_timestamp"]

    cutoff = timeline[-2]["effective_timestamp"]
    resolved = resolve_intelligence_timeline(timeline, cutoff)
    assert resolved["effective_timestamp"].replace(tzinfo=timezone.utc) == cutoff


def test_walk_forward_stack_resolver_constructs_stateful_timeframes():
    candles = _candles(65)
    resolver = _build_in_memory_stack_resolver(
        "DOGEUSDT",
        {
            "1h": candles,
            "4h": candles,
            "1d": candles,
        },
    )

    result = resolver(candles[-1].close_time)

    assert result["status"] == "READY"
    assert {
        item["timeframe"]
        for item in result["timeframes"]
    } == {"1h", "4h", "1d"}
    assert all(item["intelligence"].get("signal") for item in result["timeframes"])


def test_stack_history_scales_to_equal_time_coverage_plus_warmup():
    assert _stack_history_limit("1h", "1h", 12_960) == 13_260
    assert _stack_history_limit("1h", "4h", 12_960) == 3_540
    assert _stack_history_limit("1h", "1d", 12_960) == 840


def test_bounded_stack_history_uses_closed_prefix_without_future_candles():
    candles = _candles(80)
    candles[60].is_final = False
    cutoff = candles[70].close_time

    result = _build_bounded_stack_history_resolver(
        {"1h": candles},
        history_limit=10,
    )(cutoff)

    assert len(result["1h"]) == 10
    assert candles[60] not in result["1h"]
    assert result["1h"][-1] is candles[70]
    assert all(candle.close_time <= cutoff for candle in result["1h"])
