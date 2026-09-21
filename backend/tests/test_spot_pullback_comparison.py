import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.backtesting.spot_pullback_comparison import aggregate, build_policy_features, buy_hold, validate_policy
from app.backtesting.spot_pullback_research import ResearchConfig, build_features, entry_plan, exit_trigger


PLAN = json.loads((Path(__file__).resolve().parents[1] / "docs/spot-pullback-comparison-plan.json").read_text())


def candles(count=18000):
    index = pd.date_range("2023-04-01", periods=count, freq="15min", tz="UTC")
    close = 100 + np.arange(count) * .001 + np.sin(np.arange(count) / 10)
    return pd.DataFrame({"open": close - .05, "high": close + .3,
                         "low": close - .3, "close": close, "quote_volume": 10_000_000.}, index=index)


def test_control_features_match_original_exactly():
    frame = candles(9000)
    original = build_features(frame)
    control = build_policy_features(frame, None, PLAN["candidates"][0])
    for column in original.columns:
        pd.testing.assert_series_equal(original[column], control[column])


def test_hourly_signals_not_repeated_or_leaked_into_unfinished_hours():
    frame = candles()
    policy = PLAN["candidates"][3]
    out = build_policy_features(frame, None, policy)
    assert not out.loc[out.index.minute != 0, "signal"].any()
    cutoff = frame.index[17003]  # incomplete hour
    changed = frame.copy()
    changed.loc[cutoff:, ["open", "high", "low", "close"]] *= 2
    after = build_policy_features(changed, None, policy)
    pd.testing.assert_frame_equal(out.loc[:cutoff], after.loc[:cutoff])
    at = frame.index[17000].floor("h") + pd.Timedelta(hours=1)
    expected = frame.loc[at - pd.Timedelta(minutes=15), "quote_volume"]
    assert out.loc[at, "quote_volume"] == expected


def test_aggregation_excludes_incomplete_edges():
    frame = candles(10).iloc[1:]
    hourly = aggregate(frame, 60)
    assert len(hourly) == 1
    assert hourly.index[0].hour == 1


def test_policy_cap_and_expiry_change_only_intended_rules():
    config = ResearchConfig()
    signal = {"stop": 98, "atr": 1.2, "close": 99.8, "quote_volume": 1e7}
    assert entry_plan(signal, 100, 10000, 10000, 0, config)[1] == "ENTRY_PRICE_CAP"
    plan, failure = entry_plan({**signal, "entry_cap_atr": .5, "max_hold_hours": 24},
                               100, 10000, 10000, 0, config)
    assert failure is None
    assert plan["risk_budget"] <= 25
    now = pd.Timestamp("2024-01-01T00:00Z")
    plan["entry_time"] = now
    bar = {"open": 100, "low": 99.5, "high": 100.5}
    assert exit_trigger(plan, bar, now + pd.Timedelta(hours=6)) is None
    assert exit_trigger(plan, bar, now + pd.Timedelta(hours=24))[0] == "TIME_EXIT"


def test_benchmark_constant_prices_lose_exact_costs():
    frame = candles(20)
    frame[["open", "high", "low", "close"]] = 100.
    config = ResearchConfig()
    result = buy_hold({"BTCUSDT": frame, "ETHUSDT": frame}, frame.index[0], frame.index[-1], .5, config)
    expected = (.5 + .5 * (1 - .0005) * (1 - .001) / ((1 + .0005) * (1 + .001)) - 1) * 100
    assert result["return_percent"] == pytest.approx(expected)


def test_policy_cannot_enable_arbitrary_horizons():
    with pytest.raises(ValueError):
        validate_policy({**PLAN["candidates"][0], "max_hold_hours": 999})
