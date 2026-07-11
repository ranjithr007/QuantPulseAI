from datetime import datetime
from datetime import timedelta

import pytest
from fastapi import HTTPException

from app.api.v1 import backtest_api
from app.backtesting.walk_forward_validator import WalkForwardConfig
from app.backtesting.walk_forward_validator import phase2_walk_forward_defaults
from app.backtesting.walk_forward_validator import run_walk_forward


class Candle:
    def __init__(self, candle_time, price):
        self.candle_time = candle_time
        self.open_price = price
        self.high_price = price * 1.03
        self.low_price = price * 0.995
        self.close_price = price * 1.02


START = datetime(2026, 1, 1)


def candles(count):
    return [Candle(START + timedelta(minutes=index), 100 + index) for index in range(count)]


def test_expanding_walk_forward_builds_non_overlapping_oos_folds():
    result = run_walk_forward(
        candles(12),
        "LONG",
        stop_grid=[1],
        target_grid=[2],
        train_size=6,
        test_size=3,
        step_size=3,
        min_train_trades=1,
        fee_bps=0,
        slippage_bps=0,
    )

    assert result["validation_status"] == "VALID"
    assert result["fold_count"] == 2
    assert result["folds"][0]["train"]["end"] == (START + timedelta(minutes=5)).isoformat()
    assert result["folds"][0]["test"]["start"] == (START + timedelta(minutes=6)).isoformat()
    assert result["folds"][1]["train"]["end"] == (START + timedelta(minutes=8)).isoformat()
    assert result["folds"][1]["test"]["start"] == (START + timedelta(minutes=9)).isoformat()
    assert result["out_of_sample"]["total_trades"] > 0


def test_parameter_selection_never_receives_test_candles():
    calls = []

    def runner(items, signal, **options):
        calls.append(
            {
                "times": [item.candle_time for item in items],
                "stop": options["stop_percent"],
                "capital": options["initial_capital"],
            }
        )
        selected_return = 5 if options["stop_percent"] == 1 else 1
        start_capital = float(options["initial_capital"])
        final_capital = start_capital * (1 + selected_return / 100)
        return {
            "total_trades": 4,
            "total_return_percent": selected_return,
            "max_drawdown_percent": 1,
            "sharpe_ratio": 1,
            "final_capital": final_capital,
            "wins": 2,
            "losses": 2,
            "win_rate": 50,
            "profit_factor": 1,
            "expectancy_percent": 0,
            "fees_paid": 0,
            "exposure_percent": 50,
            "trades": [],
            "equity_curve": [
                {"label": items[0].candle_time.isoformat(), "equity": start_capital},
                {"label": items[-1].candle_time.isoformat(), "equity": final_capital},
            ],
        }

    result = run_walk_forward(
        candles(12),
        "LONG",
        stop_grid=[1, 2],
        target_grid=[2],
        train_size=6,
        test_size=3,
        step_size=3,
        min_train_trades=1,
        backtest_runner=runner,
    )

    training_calls = [call for call in calls if len(call["times"]) != 4]
    oos_calls = [call for call in calls if len(call["times"]) == 4]
    assert max(training_calls[0]["times"]) == START + timedelta(minutes=5)
    assert max(training_calls[1]["times"]) == START + timedelta(minutes=5)
    assert max(training_calls[2]["times"]) == START + timedelta(minutes=8)
    assert max(training_calls[3]["times"]) == START + timedelta(minutes=8)
    assert oos_calls[0]["times"] == [START + timedelta(minutes=index) for index in range(5, 9)]
    assert oos_calls[1]["times"] == [START + timedelta(minutes=index) for index in range(8, 12)]
    assert all(fold["selected_parameters"]["stop_percent"] == 1 for fold in result["folds"])


def test_rolling_mode_keeps_training_window_fixed():
    result = run_walk_forward(
        candles(12),
        "LONG",
        stop_grid=[1],
        target_grid=[2],
        train_size=6,
        test_size=3,
        step_size=3,
        mode="ROLLING",
        min_train_trades=1,
        fee_bps=0,
        slippage_bps=0,
    )

    assert [fold["train"]["candle_count"] for fold in result["folds"]] == [6, 6]
    assert result["folds"][1]["train"]["start"] == (START + timedelta(minutes=3)).isoformat()


def test_low_sample_fallback_prefers_evidence_over_no_trade_score():
    def runner(items, signal, **options):
        trades = 0 if options["stop_percent"] == 1 else 2
        return_percent = 0 if trades == 0 else -2
        capital = float(options["initial_capital"])
        return {
            "total_trades": trades,
            "total_return_percent": return_percent,
            "max_drawdown_percent": abs(return_percent),
            "sharpe_ratio": 0,
            "final_capital": capital * (1 + return_percent / 100),
            "trades": [],
            "equity_curve": [
                {"label": items[0].candle_time.isoformat(), "equity": capital},
                {"label": items[-1].candle_time.isoformat(), "equity": capital},
            ],
            "exposure_percent": 0,
        }

    result = run_walk_forward(
        candles(9),
        "LONG",
        stop_grid=[1, 2],
        target_grid=[2],
        train_size=6,
        test_size=3,
        min_train_trades=3,
        backtest_runner=runner,
    )

    assert result["validation_status"] == "LIMITED_TRAINING_TRADES"
    assert result["folds"][0]["selected_parameters"]["stop_percent"] == 2


def test_insufficient_history_returns_explainable_result():
    result = run_walk_forward(
        candles(8),
        "LONG",
        stop_grid=[1],
        target_grid=[2],
        train_size=6,
        test_size=3,
    )

    assert result["validation_status"] == "INSUFFICIENT_DATA"
    assert result["required_candle_count"] == 9
    assert result["fold_count"] == 0


def test_overlapping_test_windows_are_rejected():
    with pytest.raises(ValueError, match="overlapping"):
        WalkForwardConfig(train_size=10, test_size=5, step_size=4)


def test_walk_forward_api_forwards_validated_configuration(monkeypatch):
    captured = {}

    def execute(symbol, timeframe, signal, **options):
        captured.update(options)
        return {"engine_version": "walk_forward_v1", "fold_count": 2}

    monkeypatch.setattr(backtest_api, "execute_walk_forward", execute)
    response = backtest_api.walk_forward_validation(
        symbol="BTCUSDT",
        signal="LONG",
        timeframe="15m",
        limit=800,
        train_size=200,
        test_size=50,
        step_size=50,
        mode="ROLLING",
        min_train_trades=4,
        stop_grid="0.5,1",
        target_grid="1.5,2",
        initial_capital=20_000,
        position_size_percent=50,
        fee_bps=5,
        slippage_bps=3,
    )

    assert response["source"] == "walk_forward_validation_v1"
    assert response["result"]["fold_count"] == 2
    assert captured["stop_grid"] == [0.5, 1.0]
    assert captured["target_grid"] == [1.5, 2.0]
    assert captured["mode"] == "ROLLING"


def test_walk_forward_api_rejects_bad_grid_and_overlap():
    with pytest.raises(HTTPException) as grid_error:
        backtest_api._parse_grid("1,nope", "stop_grid")
    assert grid_error.value.status_code == 422

    with pytest.raises(HTTPException) as overlap_error:
        backtest_api.walk_forward_validation(
            symbol="BTCUSDT",
            signal="LONG",
            timeframe="15m",
            limit=800,
            train_size=200,
            test_size=50,
            step_size=25,
            mode="EXPANDING",
            min_train_trades=3,
            stop_grid="1",
            target_grid="2",
            initial_capital=10_000,
            position_size_percent=100,
            fee_bps=4,
            slippage_bps=2,
        )
    assert overlap_error.value.status_code == 422


def test_walk_forward_api_uses_phase2_defaults_for_official_timeframe(monkeypatch):
    captured = {}

    def execute(symbol, timeframe, signal, **options):
        captured.update(options)
        return {"engine_version": "walk_forward_v1", "fold_count": 6}

    defaults = phase2_walk_forward_defaults("1h")
    monkeypatch.setattr(backtest_api, "execute_walk_forward", execute)

    response = backtest_api.walk_forward_validation(
        symbol="BTCUSDT",
        signal="LONG",
        timeframe="1h",
    )

    assert response["result"]["fold_count"] == 6
    assert captured["train_size"] == defaults["train_size"]
    assert captured["test_size"] == defaults["test_size"]
    assert captured["step_size"] == defaults["step_size"]
    assert captured["limit"] == defaults["minimum_fold_candles"]


def test_walk_forward_contract_summary_marks_official_config_as_pass_with_six_folds():
    defaults = phase2_walk_forward_defaults("1d")
    result = run_walk_forward(
        candles(defaults["minimum_fold_candles"]),
        "LONG",
        timeframe="1d",
        stop_grid=[1],
        target_grid=[2],
        train_size=defaults["train_size"],
        test_size=defaults["test_size"],
        step_size=defaults["step_size"],
        min_train_trades=1,
        fee_bps=0,
        slippage_bps=0,
    )

    contract = result["validation_contract"]
    assert contract["timeframe_status"] == "OFFICIAL"
    assert contract["configuration_matches_contract"] is True
    assert contract["minimum_fold_requirement"] == 6
    assert contract["contract_status"] == "PASS"
