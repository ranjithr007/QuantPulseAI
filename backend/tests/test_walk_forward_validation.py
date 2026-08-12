from collections import Counter
from datetime import datetime
from datetime import timedelta

import pytest
from fastapi import HTTPException

from app.api.v1 import backtest_api
from app.backtesting.walk_forward_validator import WalkForwardConfig
from app.backtesting.walk_forward_validator import phase2_walk_forward_defaults
from app.backtesting.walk_forward_validator import run_walk_forward
from app.backtesting.walk_forward_validator import _merge_directional_entry_funnel
from app.backtesting.walk_forward_validator import _serialize_directional_entry_funnel


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
            "decision_summary": {
                "evaluated": len(items),
                "signals": {"WAIT": len(items)},
                "rejections": {"REGIME_NOT_BULLISH": len(items)},
                "regimes": {"RANGE_NEUTRAL": len(items)},
                "regime_directions": {"NEUTRAL": len(items)},
                "independent_gate_pass_counts": {"MARKET_DATA": len(items)},
                "rejection_combinations": {
                    "REGIME_NOT_BULLISH": len(items),
                },
                "feature_score_distributions": {
                    "final_score": {
                        "count": len(items),
                        "minimum": 50,
                        "maximum": 50,
                        "average": 50,
                        "value_sum": 50 * len(items),
                        "buckets": {"50-59": len(items)},
                    }
                },
                "master_signal_diagnostics": {
                    "regime_gate_pass_decisions": {
                        "evaluated": len(items),
                        "signals": {"WAIT": len(items)},
                        "biases": {"NEUTRAL": len(items)},
                        "score_distribution": {
                            "count": len(items),
                            "minimum": 10,
                            "maximum": 10,
                            "average": 10,
                            "value_sum": 10 * len(items),
                            "buckets": {"10-19": len(items)},
                        },
                        "components": {
                            "feature": {
                                "values": {"SIDEWAYS": len(items)},
                                "score_distribution": {
                                    "count": len(items),
                                    "minimum": 1,
                                    "maximum": 1,
                                    "average": 1,
                                    "value_sum": len(items),
                                    "buckets": {"00-09": len(items)},
                                },
                            }
                        },
                    }
                },
            },
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
    gate_diagnostics = result["out_of_sample"]["gate_diagnostics"]
    assert gate_diagnostics["regimes"] == {"RANGE_NEUTRAL": 8}
    assert gate_diagnostics["regime_percentages"] == {"RANGE_NEUTRAL": 100.0}
    assert gate_diagnostics["regime_direction_percentages"] == {"NEUTRAL": 100.0}
    assert gate_diagnostics["independent_gate_pass_percentages"] == {"MARKET_DATA": 100.0}
    assert gate_diagnostics["rejection_combinations"] == {"REGIME_NOT_BULLISH": 8}
    assert gate_diagnostics["feature_score_distributions"]["final_score"] == {
        "count": 8,
        "minimum": 50.0,
        "maximum": 50.0,
        "average": 50.0,
        "value_sum": 400.0,
        "buckets": {"50-59": 8},
    }
    master = gate_diagnostics["master_signal_diagnostics"][
        "regime_gate_pass_decisions"
    ]
    assert master["evaluated"] == 8
    assert master["signals"] == {"WAIT": 8}
    assert master["score_distribution"]["average"] == 10.0
    assert master["components"]["feature"]["values"] == {"SIDEWAYS": 8}


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


def test_adverse_replay_uses_frozen_fold_parameters_without_reselection():
    result = run_walk_forward(
        candles(12),
        "LONG",
        stop_grid=[1, 2],
        target_grid=[2, 3],
        train_size=6,
        test_size=3,
        step_size=3,
        min_train_trades=1,
        fee_bps=8,
        slippage_bps=4,
        frozen_fold_parameters=[
            {"stop_percent": 2, "target_percent": 3},
            {"stop_percent": 1, "target_percent": 2},
        ],
    )

    assert result["validation_status"] == "VALID"
    assert result["configuration"]["selection_mode"] == "FROZEN_FOLD_PARAMETERS"
    assert [
        fold["selected_parameters"]
        for fold in result["folds"]
    ] == [
        {"stop_percent": 2.0, "target_percent": 3.0},
        {"stop_percent": 1.0, "target_percent": 2.0},
    ]
    assert all(fold["selection"]["status"] == "FROZEN" for fold in result["folds"])


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
        as_of=START,
    )

    assert response["source"] == "walk_forward_validation_v1"
    assert response["result"]["fold_count"] == 2
    assert captured["stop_grid"] == [0.5, 1.0]
    assert captured["target_grid"] == [1.5, 2.0]
    assert captured["mode"] == "ROLLING"
    assert captured["as_of_timestamp"] == START


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

    with pytest.raises(HTTPException) as frozen_error:
        backtest_api._frozen_fold_options('[{"stop_percent": 1}]')
    assert frozen_error.value.status_code == 422


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


def test_walk_forward_merges_directional_funnel_counts_across_folds():
    target = {
        "evaluated": 0,
        "candidate_regimes": Counter(),
        "cumulative_stage_counts": Counter(),
        "independent_condition_pass_counts": Counter(),
        "first_failure_counts": Counter(),
        "confirmed_candidate_score_distributions": {},
        "master_candidate_chain_audit": {
            "evaluated": 0,
            "contradiction_statuses": Counter(),
            "contradiction_trade_allowed": Counter(),
            "conflict_scores": {},
            "master_signal_scores": {},
            "master_signal_confidences": {},
            "risk_confidences": {},
            "conflict_names": Counter(),
            "conflict_severities": Counter(),
            "bias_maps": {},
            "risk_decisions": Counter(),
            "risk_reasons": Counter(),
            "executor_verdicts": Counter(),
            "current_price_availability": Counter(),
        },
        "contract": {},
    }
    incoming = {
        "evaluated": 4,
        "candidate_regimes": {"BULL_PULLBACK": 2},
        "cumulative_stage_counts": {
            "SAME_SIDE_CANDIDATE_REGIME": 2,
            "LOCAL_CONFIRMATION": 1,
            "CONFIDENCE_AT_OR_ABOVE_THRESHOLD": 1,
            "FINAL_ELIGIBLE": 0,
        },
        "independent_condition_pass_counts": {
            "SAME_SIDE_CANDIDATE_REGIME": 2,
            "LOCAL_CONFIRMATION": 1,
            "CONFIDENCE_AT_OR_ABOVE_THRESHOLD": 2,
            "FINAL_ELIGIBLE": 0,
        },
        "first_failure_counts": {"LOCAL_CONFIRMATION": 1, "FINAL_ELIGIBLE": 1},
        "confirmed_candidate_score_distributions": {
            "composite_confidence": {
                "count": 1,
                "minimum": 65,
                "maximum": 65,
                "average": 65,
                "value_sum": 65,
                "buckets": {"60-69": 1},
            }
        },
        "master_candidate_chain_audit": {
            "evaluated": 1,
            "contradiction_statuses": {"INVALIDATED": 1},
            "contradiction_trade_allowed": {"BLOCKED": 1},
            "conflict_score_distribution": {
                "count": 1,
                "minimum": 100,
                "maximum": 100,
                "average": 100,
                "value_sum": 100,
                "buckets": {"90-100": 1},
            },
            "master_signal_score_distribution": {
                "count": 1,
                "minimum": 42,
                "maximum": 42,
                "average": 42,
                "value_sum": 42,
                "buckets": {"40-49": 1},
            },
            "master_signal_confidence_distribution": {
                "count": 1,
                "minimum": 42,
                "maximum": 42,
                "average": 42,
                "value_sum": 42,
                "buckets": {"40-49": 1},
            },
            "risk_confidence_distribution": {
                "count": 1,
                "minimum": 42,
                "maximum": 42,
                "average": 42,
                "value_sum": 42,
                "buckets": {"40-49": 1},
            },
            "conflict_names": {"missing_candle": 1},
            "conflict_severities": {"critical": 1},
            "bias_maps": {"signal": {"LONG": 1}},
            "risk_decisions": {"REJECT": 1},
            "risk_reasons": {"Contradiction blocked": 1},
            "executor_verdicts": {"BLOCKED": 1},
            "current_price_availability": {"MISSING": 1},
        },
        "contract": {
            "stage_order": [
                "SAME_SIDE_CANDIDATE_REGIME",
                "LOCAL_CONFIRMATION",
                "CONFIDENCE_AT_OR_ABOVE_THRESHOLD",
                "FINAL_ELIGIBLE",
            ]
        },
    }

    _merge_directional_entry_funnel(target, incoming)
    _merge_directional_entry_funnel(target, incoming)
    result = _serialize_directional_entry_funnel(target)

    assert result["evaluated"] == 8
    assert result["candidate_regimes"] == {"BULL_PULLBACK": 4}
    assert result["cumulative_stage_counts"]["LOCAL_CONFIRMATION"] == 2
    assert result["independent_condition_pass_counts"][
        "CONFIDENCE_AT_OR_ABOVE_THRESHOLD"
    ] == 4
    assert result["first_failure_counts"] == {
        "FINAL_ELIGIBLE": 2,
        "LOCAL_CONFIRMATION": 2,
    }
    assert result["confirmed_candidate_score_distributions"][
        "composite_confidence"
    ]["count"] == 2
    assert result["confirmed_candidate_score_distributions"][
        "composite_confidence"
    ]["average"] == 65
    audit = result["master_candidate_chain_audit"]
    assert audit["evaluated"] == 2
    assert audit["conflict_names"] == {"missing_candle": 2}
    assert audit["conflict_score_distribution"]["count"] == 2
    assert audit["current_price_availability"] == {"MISSING": 2}
    assert audit["master_signal_score_distribution"]["count"] == 2
    assert audit["master_signal_confidence_distribution"]["average"] == 42
    assert audit["risk_confidence_distribution"]["average"] == 42
    assert result["contract"]["first_failures_reconcile_to_candidates"] is True
