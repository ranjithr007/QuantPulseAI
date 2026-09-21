from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from app.backtesting import spot_pullback_research as research


def candles(count=9000):
    index = pd.date_range("2024-01-01", periods=count, freq="15min", tz="UTC")
    close = 100 + np.arange(count) * .005
    return pd.DataFrame({"open": close - .02, "high": close + .2,
                         "low": close - .2, "close": close,
                         "quote_volume": 10_000_000.0}, index=index)


def test_rejects_gaps_duplicates_nan_and_impossible_prices():
    frame = candles(10)
    with pytest.raises(ValueError, match="Missing candles"):
        research.validate_candles(frame.drop(frame.index[3]))
    with pytest.raises(ValueError, match="unique"):
        research.validate_candles(pd.concat([frame, frame.iloc[[-1]]]))
    frame.iloc[2, frame.columns.get_loc("close")] = float("nan")
    with pytest.raises(ValueError, match="Nonfinite"):
        research.validate_candles(frame)
    frame = candles(10)
    frame.iloc[2, frame.columns.get_loc("high")] = 1
    with pytest.raises(ValueError, match="envelope"):
        research.validate_candles(frame)


def test_hourly_context_available_only_after_hour_close():
    frame = candles(20)
    hourly = research.hourly_context(frame)
    assert hourly.index[0] == frame.index[0] + pd.Timedelta(hours=1)
    assert hourly.iloc[0].close == frame.iloc[3].close


def test_signal_prefix_is_unchanged_when_future_prices_change():
    frame = candles()
    cutoff = frame.index[8800]
    before = research.build_features(frame)
    modified = frame.copy()
    modified.loc[cutoff:, ["open", "high", "low", "close"]] *= 4
    after = research.build_features(modified)
    pd.testing.assert_frame_equal(before.loc[:cutoff], after.loc[:cutoff])
    assert not before.signal.iloc[:8000].any()  # full trailing volatility window


def test_sizing_cost_budget_and_no_leverage():
    config = research.ResearchConfig()
    signal = {"stop": 98, "atr": 1, "close": 100, "quote_volume": 10_000_000}
    plan, reason = research.entry_plan(signal, 100, 10000, 10000, 0, config)
    assert reason is None
    assert plan["risk_budget"] <= 25 + 1e-10
    assert plan["entry"] * plan["quantity"] <= 2500
    # Default costs exceed 15% of a narrow stop, so cheap-looking tiny targets fail.
    assert research.entry_plan({**signal, "stop": 99, "atr": .5}, 100, 10000, 10000, 0, config)[1] == "COST_TO_RISK"
    assert research.entry_plan(signal, 102, 10000, 10000, 0, config)[0] is None
    with pytest.raises(ValueError):
        replace(config, risk_fraction=.1)


def test_stop_first_gap_and_time_exit_sequence():
    now = pd.Timestamp("2024-01-01T00:00Z")
    position = {"entry_time": now, "stop": 98, "target": 103}
    assert research.exit_trigger(position, {"open": 100, "low": 97, "high": 104}, now)[0] == "STOP"
    assert research.exit_trigger(position, {"open": 95, "low": 94, "high": 104}, now)[1] == 95
    later = now + pd.Timedelta(hours=6)
    assert research.exit_trigger(position, {"open": 100, "low": 97, "high": 104}, later) == ("TIME_EXIT", 100, later)


def signal_features(frame, signal_time):
    out = frame.copy()
    out.index += research.BAR
    out["signal"] = out.index == signal_time
    out["stop"] = 97.5
    out["atr"] = 1.2
    out["turnover"] = 1_000_000_000
    out["trend_exit"] = False
    return out


def test_portfolio_end_liquidation_reconciles_costs_and_never_promotes(monkeypatch):
    frame = candles(32)
    frame[["open", "close"]] = 100.
    frame["low"], frame["high"] = 99.5, 100.5
    start = frame.index[2]
    monkeypatch.setattr(research, "build_features", lambda f, btc_frame=None: signal_features(f, start))
    result = research.run_screen({"BTCUSDT": frame}, start=start,
                                 end=frame.index[10], config=research.ResearchConfig())
    assert len(result["trades"]) == 1
    trade = result["trades"][0]
    assert trade["entry_time"] == start.isoformat()
    assert trade["exit_reason"] == "END_OF_SAMPLE"
    assert trade["net_pnl"] < 0
    assert result["metrics"]["net_pnl"] == pytest.approx(trade["net_pnl"])
    assert not result["promotion_allowed"]
    assert not result["metrics"]["win_rate_above_80_validated"]


def test_two_symbols_share_risk_and_cash(monkeypatch):
    frame = candles(32)
    frame[["open", "close"]] = 100.
    frame["low"], frame["high"] = 99.5, 100.5
    start = frame.index[2]
    monkeypatch.setattr(research, "build_features", lambda f, btc_frame=None: signal_features(f, start))
    result = research.run_screen({"BTCUSDT": frame, "ETHUSDT": frame}, start=start, end=frame.index[10])
    trades = result["trades"]
    assert len(trades) == 2
    assert sum(t["risk_budget"] for t in trades) <= 50
    assert sum(t["entry"] * t["quantity"] for t in trades) <= 5000
    assert sum(t["net_pnl"] for t in trades) == pytest.approx(result["metrics"]["net_pnl"])


def test_drawdown_halt_is_latched_and_no_news_cause_invented(monkeypatch):
    frame = candles(32)
    frame[["open", "close"]] = 100.
    frame["low"], frame["high"] = 99.5, 100.5
    start = frame.index[2]
    frame.loc[frame.index[3]:, ["open", "close"]] = 20.
    frame.loc[frame.index[3]:, "low"] = 19.
    frame.loc[frame.index[3]:, "high"] = 21.
    monkeypatch.setattr(research, "build_features", lambda f, btc_frame=None: signal_features(f, start))
    result = research.run_screen({"BTCUSDT": frame}, start=start, end=frame.index[10])
    assert result["trades"][0]["exit_reason"] == "DRAWDOWN_HALT"
    assert result["metrics"]["max_drawdown_percent"] > 5  # gaps can breach budget
    assert result["risk_events"][0]["reason"] == "DRAWDOWN_HALT"


def test_loss_review_preserves_uncertainty():
    trade = dict(symbol="BTCUSDT", entry_time="x", exit_time="y", entry=100,
                 stop=98, atr=1, exit_reference=98, exit=97.9, fees=.2,
                 net_pnl=-2.3, signal_close=100, signal_quote_volume=1e7,
                 exit_reason="STOP")
    review = research.review_loss(trade)
    assert review["classification"] == "ORDINARY_LOSS_OR_UNKNOWN"
    assert review["automatic_live_change_allowed"] is False
    assert research.review_loss({**trade, "exit_reference": 96})["classification"] == "ADVERSE_GAP_OBSERVED"


def test_empty_trade_sample_not_reported_as_success():
    metrics = research.summarize([], [], 10000, 10000)
    assert metrics["net_win_rate_percent"] is None
    assert metrics["profit_factor"] is None
    assert metrics["expectancy_quote"] is None


def test_daily_entry_cap_and_stop_cooldown(monkeypatch):
    frame = candles(50)
    frame[["open", "close"]] = 100.
    frame["low"], frame["high"] = 97., 100.5
    start = frame.index[2]

    def every_bar(f, btc_frame=None):
        features = signal_features(f, start)
        features["signal"] = True
        return features

    monkeypatch.setattr(research, "build_features", every_bar)
    result = research.run_screen({"BTCUSDT": frame}, start=start, end=frame.index[-1])
    assert len(result["trades"]) == 3
    assert all(t["exit_reason"] == "STOP" for t in result["trades"])
    assert result["blocked_signals"]["STOP_COOLDOWN"] > 0
    assert result["blocked_signals"]["RISK_HALT"] > 0
    for previous, following in zip(result["trades"], result["trades"][1:]):
        assert pd.Timestamp(following["signal_time"]) > pd.Timestamp(previous["exit_time"]) + pd.Timedelta(hours=1)


def test_one_bar_delay_changes_entry_time_without_future_signal(monkeypatch):
    frame = candles(32)
    frame[["open", "close"]] = 100.
    frame["low"], frame["high"] = 99.5, 100.5
    start = frame.index[2]
    monkeypatch.setattr(research, "build_features", lambda f, btc_frame=None: signal_features(f, start))
    result = research.run_screen({"BTCUSDT": frame}, start=start, end=frame.index[10],
                                 config=research.ResearchConfig(entry_delay_bars=1))
    assert result["trades"][0]["entry_time"] == (start + research.BAR).isoformat()
    assert result["trades"][0]["signal_time"] == start.isoformat()
