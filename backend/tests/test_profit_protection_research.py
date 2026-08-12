from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
import re

import pytest

from app.api.v1.backtest_api import WALK_FORWARD_STRATEGIES
from app.backtesting import filtered_replay_engine
from app.backtesting.filtered_replay_engine import FilteredReplayConfig
from app.backtesting.filtered_replay_engine import _profit_protection_stop


def _candle(*, open_price=100, high_price=100, low_price=100, close_price=100):
    return SimpleNamespace(
        open_price=open_price,
        high_price=high_price,
        low_price=low_price,
        close_price=close_price,
        candle_time="2026-01-01T00:00:00",
    )


def test_break_even_stop_activates_after_one_r_for_long_and_short():
    long_stop, long_activated = _profit_protection_stop(
        _candle(high_price=102),
        "LONG",
        100,
        2,
        98,
        mode="BREAKEVEN_AFTER_R",
        activation_r=1,
    )
    short_stop, short_activated = _profit_protection_stop(
        _candle(low_price=98),
        "SHORT",
        100,
        2,
        102,
        mode="BREAKEVEN_AFTER_R",
        activation_r=1,
    )

    assert (long_stop, long_activated) == (100, True)
    assert (short_stop, short_activated) == (100, True)


def test_profit_protection_mode_is_validated():
    assert FilteredReplayConfig().profit_protection_mode == "NONE"
    with pytest.raises(ValueError, match="profit_protection_mode"):
        FilteredReplayConfig(profit_protection_mode="TRAIL_RANDOMLY")


def test_profit_protection_candidate_is_available_to_research_backtests():
    assert re.fullmatch(WALK_FORWARD_STRATEGIES, "PROFIT_PROTECTION_RESEARCH")


def test_protected_stop_applies_only_after_activation_candle(monkeypatch):
    monkeypatch.setattr(
        filtered_replay_engine,
        "build_candle_decision",
        lambda *_args, **_kwargs: {
            "eligible": True,
            "signal": "LONG",
            "blocked_reasons": [],
            "confidence": 70,
            "regime": "RANGE_DISTRIBUTION",
            "feature_source": "TEST",
            "point_in_time_flags": {},
            "timeframe_stack_state": "MIXED_LIGHT",
            "timeframe_stack": None,
            "features": {
                "trend_score": 70,
                "momentum_score": 60,
                "final_score": 70,
                "atr": 2,
            },
        },
    )
    candles = [_candle() for _ in range(50)]
    candles.extend(
        [
            _candle(open_price=100, high_price=102.1, low_price=99, close_price=102),
            _candle(open_price=101, high_price=101.5, low_price=99.9, close_price=100),
        ]
    )
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for index, candle in enumerate(candles):
        candle.candle_time = start + timedelta(hours=index)

    result = filtered_replay_engine.run_filtered_replay(
        candles,
        "LONG",
        min_confidence=0,
        stop_atr_multiple=1,
        target_atr_multiple=3,
        fee_bps=0,
        slippage_bps=0,
        cooldown_candles=0,
        profit_protection_mode="BREAKEVEN_AFTER_R",
        profit_protection_activation_r=1,
    )

    trade = result["trades"][0]
    assert trade["exit_reason"] == "PROTECTED_STOP"
    assert trade["exit"] == 100
    assert trade["profit_protection"]["activated"] is True
    assert trade["profit_protection"]["activation_applies_from_next_candle"] is True
    decision_summary = result["decision_summary"]
    assert sum(decision_summary["regimes"].values()) == decision_summary["evaluated"]
    assert decision_summary["regime_percentages"] == {"RANGE_DISTRIBUTION": 100.0}
    assert decision_summary["regime_direction_percentages"] == {"BEARISH": 100.0}
    assert decision_summary["rejection_combinations"] == {"PASS": 1}
    assert decision_summary["independent_gate_pass_percentages"][
        "ALL_PRE_ENTRY_GATES"
    ] == 100.0
    assert decision_summary["feature_score_distributions"]["confidence"][
        "average"
    ] == 70.0
