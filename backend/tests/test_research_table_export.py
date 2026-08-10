import csv
import hashlib
from pathlib import Path

import pytest

from app.api.v1 import backtest_api
from app.backtesting.research_table_export import build_cluster_research_tables
from app.backtesting.research_table_export import persist_cluster_research_tables


def _portfolio_result():
    return {
        "engine_version": "portfolio_replay_v1",
        "symbols": ["BTCUSDT", "DOGEUSDT"],
        "timeframe": "1h",
        "signal": "LONG",
        "trades": [
            {
                "symbol": "DOGEUSDT",
                "cluster": "ALT_BETA",
                "side": "LONG",
                "decision_time": "2026-01-01T00:00:00+00:00",
                "entry_time": "2026-01-01T01:00:00+00:00",
                "exit_time": "2026-01-01T03:00:00+00:00",
                "entry": 0.1,
                "exit": 0.11,
                "stop": 0.095,
                "target": 0.11,
                "result": "WIN",
                "exit_reason": "TARGET",
                "loss_class": None,
                "confidence": 75,
                "regime": "TRENDING_BULL",
                "trend_score": 70,
                "momentum_score": 65,
                "feature_score": 68,
                "atr": 0.003,
                "feature_source": "POINT_IN_TIME",
                "timeframe_stack": {"1h": "LONG", "4h": "LONG", "1d": "LONG"},
                "duration_candles": 2,
                "gross_pnl": 105,
                "fees": 5,
                "pnl": 100,
                "pnl_percent": 1,
                "sizing": {"notional": 5_000},
                "execution_costs": {"funding_payment": 1},
                "liquidation": {"status": "NOT_LIQUIDATED"},
                "excursions": {"mfe_r": 2.1, "mae_r": -0.4},
                "portfolio_state_at_entry": {
                    "open_positions": 1,
                    "gross_exposure": 5_000,
                    "gross_exposure_percent": 50,
                    "cluster_exposure": 5_000,
                    "cluster_exposure_percent": 50,
                },
            }
        ],
        "rejected_candidates": [
            {
                "symbol": "BTCUSDT",
                "side": "LONG",
                "entry_time": "2026-01-01T01:00:00+00:00",
                "reason": "PORTFOLIO_MAX_CLUSTER_EXPOSURE",
            }
        ],
    }


def test_research_tables_separate_entry_state_from_outcomes():
    export = build_cluster_research_tables(_portfolio_result())

    market_row = export["tables"]["market_state"][0]
    path_row = export["tables"]["trade_paths"][0]
    behavior = {
        row["symbol"]: row
        for row in export["tables"]["symbol_behavior"]
    }

    assert "pnl" not in market_row
    assert "result" not in market_row
    assert market_row["timeframe_stack"]["1d"] == "LONG"
    assert path_row["pnl"] == 100
    assert path_row["mfe_r"] == 2.1
    assert behavior["DOGEUSDT"]["win_rate"] == 100
    assert behavior["BTCUSDT"]["rejected_count"] == 1
    assert export["point_in_time_policy"]["market_state"] == (
        "ENTRY_INFORMATION_ONLY"
    )


def test_research_export_writes_schema_stable_csvs_and_hashed_manifest(tmp_path):
    artifact = persist_cluster_research_tables(
        _portfolio_result(),
        output_dir=tmp_path,
        as_of="2026-01-02T03:04:05+00:00",
    )

    assert artifact["saved"] is True
    assert artifact["row_counts"] == {
        "market_state": 1,
        "symbol_behavior": 2,
        "correlation_exposure": 1,
        "trade_paths": 1,
    }
    assert Path(artifact["manifest_path"]).exists()
    for record in artifact["files"].values():
        path = tmp_path / record["name"]
        assert path.exists()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]

    market_path = tmp_path / artifact["files"]["market_state"]["name"]
    with market_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["symbol"] == "DOGEUSDT"
    assert "pnl" not in rows[0]


def test_research_export_api_accepts_wrapped_portfolio_result(monkeypatch):
    captured = {}

    def persist(result):
        captured.update(result)
        return {"saved": True, "artifact_id": "test"}

    monkeypatch.setattr(
        backtest_api,
        "persist_cluster_research_tables",
        persist,
    )
    response = backtest_api.export_portfolio_research_tables(
        {"result": _portfolio_result()}
    )

    assert response["source"] == "portfolio_research_export_v1"
    assert response["artifact"]["saved"] is True
    assert captured["engine_version"] == "portfolio_replay_v1"


def test_research_export_api_rejects_non_portfolio_payload():
    with pytest.raises(Exception) as error:
        backtest_api.export_portfolio_research_tables(
            {"engine_version": "filtered_replay_v1", "trades": []}
        )

    assert error.value.status_code == 422
