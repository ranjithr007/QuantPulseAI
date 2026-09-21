import numpy as np
import pandas as pd
import pytest

from app.backtesting.spot_range_reversion import build_range_features, range_indicators
from app.backtesting.spot_pullback_research import ResearchConfig, entry_plan, exit_trigger


def frame(count=6000):
    index = pd.date_range("2023-04-01", periods=count, freq="15min", tz="UTC")
    close = 100 + 2 * np.sin(np.arange(count) / 25)
    return pd.DataFrame({"open": close - .1, "high": close + .5, "low": close - .5,
                         "close": close, "quote_volume": 1e7}, index=index)


def test_wilder_seed_and_directional_adx():
    data = frame(60)
    data["close"] = 100 + np.arange(60)
    data["open"] = data.close
    data["high"], data["low"] = data.close + .5, data.close - .5
    out = range_indicators(data)
    assert out.atr.iloc[:14].isna().all()
    assert out.atr.iloc[14] == 1.5
    assert out.adx.iloc[:27].isna().all()
    assert out.adx.iloc[27] == pytest.approx(100.)
    data[["open", "high", "low", "close"]] = 100.
    flat = range_indicators(data)
    assert flat.adx.iloc[27] == 0


def test_no_future_candles_and_no_repeated_hourly_signal():
    data = frame()
    before = build_range_features(data)
    cutoff = data.index[5303]
    changed = data.copy()
    changed.loc[cutoff:, ["open", "high", "low", "close"]] *= 2
    after = build_range_features(changed)
    pd.testing.assert_frame_equal(before.loc[:cutoff], after.loc[:cutoff])
    assert not before.loc[before.index.minute != 0, "signal"].any()
    assert not before.signal.iloc[:3999].any()  # 250 complete 4h candles


def test_fixed_mean_target_net_reward_and_stop_distance():
    signal = {"stop": 97.5, "atr": 1., "close": 100., "quote_volume": 1e7,
              "fixed_target": 105., "max_stop_atr": 3., "entry_cap_atr": .25,
              "max_hold_hours": 24, "regime_exit_reason": "RANGE_BREAK"}
    plan, reason = entry_plan(signal, 100, 10000, 10000, 0, ResearchConfig())
    assert reason is None
    assert plan["target"] == 105.
    assert plan["target"] != plan["entry"] + 1.5 * (plan["entry"] - plan["stop"])
    assert plan["risk_budget"] <= 25
    assert entry_plan({**signal, "fixed_target": 103}, 100, 10000, 10000, 0, ResearchConfig())[1] == "NET_REWARD_RISK"
    limited, reason = entry_plan(signal, 100, 10000, 10000, 0, ResearchConfig(), gross_exposure=4990)
    assert reason is None
    assert limited["quantity"] * limited["entry"] <= 10 + 1e-10


def test_regime_exit_is_at_next_executable_open_and_target_stays_fixed():
    now = pd.Timestamp("2024-01-01T00:00Z")
    position = {"entry_time": now, "stop": 98, "target": 105, "max_hold_hours": 24,
                "regime_exit_reason": "RANGE_BREAK"}
    bar = {"open": 101, "low": 99, "high": 106}
    assert exit_trigger(position, bar, now, True) == ("RANGE_BREAK", 101, now)
    assert exit_trigger(position, bar, now, False)[0] == "TARGET"
