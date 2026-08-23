import json

import pytest

from app.backtesting.loss_cluster_analysis import build_loss_cluster_report
from app.backtesting.loss_cluster_analysis import generate_loss_cluster_artifacts
from app.backtesting.loss_cluster_analysis import load_walk_forward_trades
from app.backtesting.loss_cluster_analysis import markdown_loss_cluster_report


def _trade(
    pnl,
    *,
    confidence=45,
    regime="TRENDING_BULL",
    exit_reason="STOP_LOSS",
    gross_pnl=None,
):
    return {
        "side": "LONG",
        "pnl": pnl,
        "gross_pnl": pnl if gross_pnl is None else gross_pnl,
        "pnl_percent": pnl / 100,
        "confidence": confidence,
        "regime": regime,
        "exit_reason": exit_reason,
        "exit_legs": [{"reason": exit_reason}],
        "execution_costs": {"total": 2.5},
        "staged_exit": {"policy": "STAGED_PERCENTAGE_V1"},
    }


def _write_run(tmp_path, trades):
    run_dir = tmp_path / "complete_walk_forward_test"
    artifact_dir = tmp_path / "phase2_validation_reports"
    run_dir.mkdir()
    artifact_dir.mkdir()
    artifact_id = "BTCUSDT_1h_LONG_test"
    artifact_path = artifact_dir / f"{artifact_id}.json"
    artifact_path.write_text(
        json.dumps(
            {
                "scope": {
                    "symbol": "BTCUSDT",
                    "timeframe": "1h",
                    "signal": "LONG",
                },
                "walk_forward_result": {
                    "backtest_engine_version": "filtered_replay_v2_staged_exit_parity",
                    "out_of_sample": {"trades": trades},
                },
            }
        ),
        encoding="utf-8",
    )
    consolidated_path = run_dir / "consolidated_walk_forward_report.json"
    consolidated = {
        "source": "complete_walk_forward_validation_v4_staged_exit_parity",
        "as_of": "2026-08-23T15:00:00+00:00",
        "scope": {"grid": {"stop_loss_percent": 0.75}},
        "records": [
            {
                "symbol": "BTCUSDT",
                "timeframe": "1h",
                "signal": "LONG",
                "status": "COMPLETED",
                "oos_total_trades": len(trades),
                "artifact": {
                    "artifact_id": artifact_id,
                    "json_path": "/old/container/path.json",
                },
            }
        ],
    }
    consolidated_path.write_text(json.dumps(consolidated), encoding="utf-8")
    return consolidated_path, consolidated


def test_load_walk_forward_trades_resolves_relocated_artifact(tmp_path):
    consolidated_path, consolidated = _write_run(tmp_path, [_trade(-10), _trade(20)])

    trades, ingestion = load_walk_forward_trades(
        consolidated,
        consolidated_path=consolidated_path,
    )

    assert len(trades) == 2
    assert trades[0]["symbol"] == "BTCUSDT"
    assert trades[0]["timeframe"] == "1h"
    assert ingestion["ledger_complete"] is True
    assert ingestion["engine_versions"] == ["filtered_replay_v2_staged_exit_parity"]


def test_build_report_attributes_losses_costs_and_confidence_bands():
    trades = [
        {**_trade(-20, confidence=45), "symbol": "BTCUSDT", "timeframe": "1h"},
        {**_trade(10, confidence=65, exit_reason="TARGET2"), "symbol": "ETHUSDT", "timeframe": "2h"},
        {**_trade(-5, confidence=None, gross_pnl=1), "symbol": "ETHUSDT", "timeframe": "2h"},
    ]
    report = build_loss_cluster_report(
        {"scope": {"grid": {}}, "source": "test"},
        trades,
        ingestion={"loaded_trades": 3, "ledger_complete": True},
    )

    assert report["overall"]["trade_count"] == 3
    assert report["overall"]["net_pnl"] == -15
    assert report["overall"]["execution_costs"] == 7.5
    assert report["overall"]["cost_flipped_trades"] == 1
    confidence = {
        item["cluster"]: item for item in report["breakdowns"]["confidence_band"]
    }
    assert confidence["40-49.99"]["net_pnl"] == -20
    assert confidence["60-69.99"]["net_pnl"] == 10
    assert confidence["UNKNOWN"]["net_pnl"] == -5
    assert report["governance"]["production_policy_changed"] is False


def test_research_hypotheses_require_minimum_sample_and_do_not_add_blockers():
    trades = [
        {
            **_trade(-10, confidence=45, regime="RANGE_DISTRIBUTION"),
            "symbol": "XRPUSDT",
            "timeframe": "1h",
        }
        for _ in range(5)
    ]
    report = build_loss_cluster_report(
        {"scope": {"grid": {}}, "source": "test"},
        trades,
        ingestion={"loaded_trades": 5, "ledger_complete": True},
    )

    assert any(
        item["dimension"] == "regime"
        and item["cluster"] == "RANGE_DISTRIBUTION"
        for item in report["research_hypotheses"]
    )
    assert report["governance"]["automatic_blockers_added"] is False
    assert report["governance"]["holdout_validation_required"] is True


def test_generate_artifacts_writes_json_and_markdown(tmp_path):
    consolidated_path, _ = _write_run(tmp_path, [_trade(-10), _trade(20)])

    generated = generate_loss_cluster_artifacts(consolidated_path)

    assert generated["report"]["overall"]["trade_count"] == 2
    assert "Loss-Cluster Report" in open(
        generated["markdown_path"], encoding="utf-8"
    ).read()
    markdown = markdown_loss_cluster_report(generated["report"])
    assert "No live-trading promotion is authorized" in markdown
    assert "Production policy changed: No" in markdown


def test_missing_full_artifact_fails_closed(tmp_path):
    consolidated = {
        "records": [
            {
                "status": "COMPLETED",
                "symbol": "BTCUSDT",
                "timeframe": "1h",
                "signal": "LONG",
                "oos_total_trades": 1,
                "artifact": {"artifact_id": "missing"},
            }
        ]
    }

    with pytest.raises(ValueError, match="requires every completed full artifact"):
        load_walk_forward_trades(
            consolidated,
            consolidated_path=tmp_path / "run" / "consolidated.json",
        )
