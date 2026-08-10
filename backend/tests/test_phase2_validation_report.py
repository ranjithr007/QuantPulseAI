from app.api.v1 import backtest_api
from app.backtesting.phase2_validation_report import build_phase2_validation_report


def _walk_forward_result():
    return {
        "validation_status": "VALID",
        "fold_count": 6,
        "out_of_sample": {
            "total_trades": 12,
            "total_return_percent": 14.2,
            "profit_factor": 1.45,
            "win_rate": 50.0,
            "max_drawdown_percent": 12.5,
            "sharpe_ratio": 1.18,
            "trades": [
                {"pnl_percent": 2.0},
                {"pnl_percent": 1.5},
                {"pnl_percent": -1.0},
                {"pnl_percent": 2.4},
                {"pnl_percent": -1.2},
                {"pnl_percent": 1.7},
            ],
        },
        "validation_contract": {
            "contract_version": "phase2_proof_of_edge_v1",
            "timeframe": "1h",
            "timeframe_status": "OFFICIAL",
            "official_timeframes": ["1d", "1h", "4h"],
            "supporting_timeframes": ["15m", "5m"],
            "target_windows_days": {
                "train_window_days": 180,
                "test_window_days": 60,
                "step_days": 30,
                "minimum_folds": 6,
            },
            "required_candle_count_for_minimum_folds": 5040,
            "minimum_fold_requirement": 6,
            "contract_status": "PASS",
            "configuration_matches_contract": True,
            "issues": [],
        },
    }


def test_phase2_validation_report_marks_current_system_partial_when_gate_inputs_are_missing():
    report = build_phase2_validation_report(
        _walk_forward_result(),
        symbol="DOGEUSDT",
        timeframe="1h",
        signal="LONG",
    )

    assert report["report_version"] == "phase2_validation_report_v1"
    assert report["overall_status"] == "PARTIAL"
    assert report["architecture_gate"]["status"] == "INSUFFICIENT_EVIDENCE"
    assert report["derived_metrics"]["out_of_sample_payoff_ratio"] == 1.7273
    names = {item["name"]: item for item in report["architecture_gate"]["checks"]}
    assert names["out_of_sample_win_rate"]["status"] == "PASS"
    assert names["out_of_sample_annualized_sharpe"]["status"] == "NOT_STARTED"
    assert names["auditable_paper_days"]["status"] == "INSUFFICIENT_EVIDENCE"


def test_phase2_validation_report_api_wraps_walk_forward_and_report(monkeypatch):
    captured = {}

    def execute(symbol, timeframe, signal, **options):
        captured.update({"symbol": symbol, "timeframe": timeframe, "signal": signal, **options})
        return _walk_forward_result()

    monkeypatch.setattr(backtest_api, "execute_walk_forward", execute)

    payload = backtest_api.phase2_validation_report(
        symbol="DOGEUSDT",
        signal="LONG",
        timeframe="1h",
    )

    assert payload["source"] == "phase2_validation_report_v1"
    assert payload["report"]["overall_status"] == "PARTIAL"
    assert payload["report"]["scope"]["symbol"] == "DOGEUSDT"
    assert captured["timeframe"] == "1h"
    assert captured["train_size"] > 0
    assert captured["test_size"] > 0
    assert captured["step_size"] > 0
