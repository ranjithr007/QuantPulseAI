from datetime import datetime
from datetime import timedelta

import pytest

from app.api.v1 import backtest_api
from app.backtesting.backtest_engine import BacktestConfig
from app.backtesting.backtest_engine import run_backtest


class Candle:
    def __init__(self, candle_time, open_price, high_price, low_price, close_price):
        self.candle_time = candle_time
        self.open_price = open_price
        self.high_price = high_price
        self.low_price = low_price
        self.close_price = close_price


START = datetime(2026, 1, 1)


def candle(offset, open_price=100, high_price=101, low_price=99, close_price=100):
    return Candle(
        START + timedelta(minutes=offset),
        open_price,
        high_price,
        low_price,
        close_price,
    )


def test_enters_on_next_candle_and_ignores_decision_candle_range():
    candles = [
        candle(0, high_price=200, low_price=50),
        candle(1, high_price=100.5, low_price=99.5),
        candle(2, high_price=103, low_price=100, close_price=102),
    ]

    result = run_backtest(candles, "LONG", fee_bps=0, slippage_bps=0)

    assert result["engine_version"] == "backtester_v2"
    assert result["total_trades"] == 1
    assert result["trades"][0]["entry_time"] == candles[1].candle_time.isoformat()
    assert result["trades"][0]["exit_reason"] == "TARGET"
    assert result["trades"][0]["result"] == "WIN"


def test_sorts_repository_descending_candles_before_replay():
    candles = [
        candle(2, high_price=103, low_price=100, close_price=102),
        candle(1, high_price=100.5, low_price=99.5),
        candle(0),
    ]

    result = run_backtest(candles, "LONG", fee_bps=0, slippage_bps=0)

    assert result["trades"][0]["entry_time"] == candle(1).candle_time.isoformat()


def test_stop_wins_when_stop_and_target_touch_in_same_candle():
    result = run_backtest(
        [candle(0), candle(1, open_price=100, high_price=103, low_price=98)],
        "LONG",
        fee_bps=0,
        slippage_bps=0,
    )

    trade = result["trades"][0]
    assert trade["exit_reason"] == "STOP"
    assert trade["result"] == "LOSS"
    assert trade["exit"] == pytest.approx(99)


def test_reentry_waits_until_the_candle_after_an_exit():
    result = run_backtest(
        [
            candle(0),
            candle(1, high_price=103, low_price=100, close_price=102),
            candle(2, open_price=102, high_price=105, low_price=102, close_price=104),
        ],
        "LONG",
        fee_bps=0,
        slippage_bps=0,
    )

    assert result["total_trades"] == 2
    assert result["trades"][0]["exit_time"] == candle(1).candle_time.isoformat()
    assert result["trades"][1]["entry_time"] == candle(2).candle_time.isoformat()


def test_fees_and_slippage_are_adverse_and_reported():
    candles = [candle(0), candle(1, high_price=100.5, low_price=99.5, close_price=100)]

    frictionless = run_backtest(candles, "LONG", fee_bps=0, slippage_bps=0)
    realistic = run_backtest(candles, "LONG", fee_bps=4, slippage_bps=2)

    assert frictionless["final_capital"] == 10_000
    assert realistic["final_capital"] < frictionless["final_capital"]
    assert realistic["fees_paid"] > 0
    assert realistic["trades"][0]["entry"] > 100
    assert realistic["trades"][0]["exit"] < 100


def test_open_position_closes_at_end_of_data():
    result = run_backtest(
        [candle(0), candle(1, high_price=101, low_price=99, close_price=100.5)],
        "LONG",
        stop_percent=5,
        target_percent=5,
        fee_bps=0,
        slippage_bps=0,
    )

    assert result["trades"][0]["exit_reason"] == "END_OF_DATA"
    assert result["trades"][0]["exit"] == pytest.approx(100.5)


def test_config_rejects_invalid_risk_and_cost_inputs():
    with pytest.raises(ValueError):
        BacktestConfig(initial_capital=0)
    with pytest.raises(ValueError):
        BacktestConfig(position_size_percent=101)
    with pytest.raises(ValueError):
        BacktestConfig(fee_bps=-1)


def test_summary_forwards_v2_assumptions(monkeypatch):
    captured = {}

    def execute(symbol, timeframe, trade_plan, signal, **options):
        captured.update(options)
        return {"engine_version": "backtester_v2", "total_trades": 0}

    monkeypatch.setattr(backtest_api, "execute_backtest", execute)
    response = backtest_api.backtest_summary(
        symbol="BTCUSDT",
        signal="LONG",
        timeframe="15m",
        limit=750,
        initial_capital=25_000,
        position_size_percent=50,
        stop_percent=1.5,
        target_percent=3,
        fee_bps=5,
        slippage_bps=3,
    )

    assert response["source"] == "backtest_summary_v2"
    assert response["result"]["engine_version"] == "backtester_v2"
    assert captured == {
        "limit": 750,
        "initial_capital": 25_000,
        "position_size_percent": 50,
        "stop_percent": 1.5,
        "target_percent": 3,
        "fee_bps": 5,
        "slippage_bps": 3,
    }
