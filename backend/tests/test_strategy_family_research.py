import pytest

from app.api.v1 import backtest_api
from app.backtesting.strategy_family_research import R5ResearchThresholds
from app.backtesting.strategy_family_research import build_r5_strategy_evidence


def _trades():
    records = []
    for index in range(12):
        won = index % 4 != 0
        records.append(
            {
                "symbol": ("DOGEUSDT", "BTCUSDT", "ETHUSDT")[index % 3],
                "fold": (index % 6) + 1,
                "regime": "TRENDING_BULL" if index % 2 else "TRENDING_BEAR",
                "cluster": "ALT" if index % 3 == 0 else "MAJOR",
                "confidence": 65 + (index % 3) * 10,
                "loss_class": None if won else "WRONG_DIRECTION",
                "entry_time": f"2026-{(index % 3) + 1:02d}-01T01:00:00+00:00",
                "exit_time": f"2026-{(index % 3) + 1:02d}-01T02:00:00+00:00",
                "pnl": 20 if won else -10,
                "pnl_percent": 0.2 if won else -0.1,
            }
        )
    return records


def _walk_forward():
    return {
        "engine_version": "walk_forward_v1",
        "strategy": "DOGE_SHORT_BASELINE",
        "signal": "SHORT",
        "fold_count": 6,
        "folds": [
            {
                "fold": fold,
                "selected_parameters": {
                    "stop_percent": 1,
                    "target_percent": 2,
                },
                "out_of_sample": {
                    "total_return_percent": 2,
                },
            }
            for fold in range(1, 7)
        ],
        "robustness": {"profitable_folds": 6},
        "out_of_sample": {
            "total_trades": 12,
            "trades": _trades(),
            "profit_factor": 2,
            "expectancy_percent": 0.1,
            "max_drawdown_percent": 10,
            "annualized_sharpe": 1.5,
            "total_return_percent": 12,
            "win_rate": 66.67,
        },
        "configuration": {
            "train_size": 100,
            "test_size": 20,
            "step_size": 20,
            "mode": "EXPANDING",
            "min_train_trades": 1,
            "stop_grid": [1],
            "target_grid": [2],
            "initial_capital": 10_000,
            "position_size_percent": 25,
            "fee_bps": 4,
            "slippage_bps": 2,
        },
    }


def _adverse_cost_result(*, positive=True):
    result = _walk_forward()
    result["configuration"]["fee_bps"] = 8
    result["configuration"]["slippage_bps"] = 4
    result["out_of_sample"] = {
        "total_return_percent": 3 if positive else -1,
        "expectancy_percent": 0.02 if positive else -0.01,
    }
    return result


def _thresholds():
    return R5ResearchThresholds(
        out_of_sample_trades_minimum=12,
        preferred_out_of_sample_trades=12,
        profit_concentration_maximum_percent=40,
    )


def test_r5_evidence_passes_complete_diversified_candidate():
    evidence = build_r5_strategy_evidence(
        _walk_forward(),
        adverse_cost_result=_adverse_cost_result(),
        thresholds=_thresholds(),
    )

    gates = {gate["name"]: gate for gate in evidence["gates"]}
    assert evidence["status"] == "PASS"
    assert gates["minimum_walk_forward_folds"]["status"] == "PASS"
    assert gates["positive_under_adverse_costs"]["status"] == "PASS"
    assert evidence["profit_concentration"]["symbol"]["maximum_share_percent"] < 40
    assert len(evidence["decompositions"]["confidence"]) == 3


def test_r5_evidence_fails_catastrophic_fold_and_concentrated_profit():
    result = _walk_forward()
    result["folds"][0]["out_of_sample"]["total_return_percent"] = -25
    for trade in result["out_of_sample"]["trades"]:
        trade["symbol"] = "DOGEUSDT"

    evidence = build_r5_strategy_evidence(
        result,
        adverse_cost_result=_adverse_cost_result(positive=False),
        thresholds=_thresholds(),
    )

    gates = {gate["name"]: gate for gate in evidence["gates"]}
    assert evidence["status"] == "FAIL"
    assert gates["no_catastrophic_fold"]["status"] == "FAIL"
    assert gates["symbol_profit_concentration"]["status"] == "FAIL"
    assert gates["positive_under_adverse_costs"]["status"] == "FAIL"


def test_r5_evidence_requires_separate_adverse_cost_run():
    evidence = build_r5_strategy_evidence(
        _walk_forward(),
        thresholds=_thresholds(),
    )
    gates = {gate["name"]: gate for gate in evidence["gates"]}

    assert evidence["status"] == "INSUFFICIENT_EVIDENCE"
    assert gates["positive_under_adverse_costs"]["status"] == (
        "INSUFFICIENT_EVIDENCE"
    )


def test_r5_evidence_reports_truth_repair_baseline_delta():
    evidence = build_r5_strategy_evidence(
        _walk_forward(),
        adverse_cost_result=_adverse_cost_result(),
        thresholds=_thresholds(),
        prior_baseline={
            "total_return_percent": -77.3609,
            "profit_factor": 0.93,
            "win_rate": 37.22,
            "max_drawdown_percent": 84.2653,
        },
    )

    comparison = evidence["baseline_comparison"]["metrics"]
    assert comparison["total_return_percent"]["delta"] == 89.3609
    assert comparison["profit_factor"]["delta"] == 1.07


def test_r5_adverse_cost_run_requires_identical_fold_selections():
    adverse = _adverse_cost_result()
    adverse["folds"][0]["selected_parameters"]["target_percent"] = 3

    evidence = build_r5_strategy_evidence(
        _walk_forward(),
        adverse_cost_result=adverse,
        thresholds=_thresholds(),
    )
    gate = {
        item["name"]: item
        for item in evidence["gates"]
    }["positive_under_adverse_costs"]

    assert gate["status"] == "INSUFFICIENT_EVIDENCE"
    assert gate["actual"]["fold_selections_match"] is False


def test_r5_evidence_api_rejects_non_walk_forward_payload():
    with pytest.raises(Exception) as error:
        backtest_api.r5_strategy_evidence(
            {"walk_forward_result": {"engine_version": "filtered_replay_v1"}}
        )

    assert error.value.status_code == 422
