import json
from datetime import datetime
from pathlib import Path

from app.api.v1 import backtest_api
from app.backtesting import phase2_validation_artifacts as phase2_artifacts
from app.backtesting.phase2_validation_artifacts import list_phase2_validation_artifacts
from app.backtesting.phase2_validation_artifacts import load_phase2_validation_artifact
from app.backtesting.phase2_validation_artifacts import persist_phase2_validation_artifact
from app.backtesting.phase2_validation_artifacts import summarize_phase2_validation_artifacts


def _report():
    return {
        "overall_status": "PARTIAL",
        "architecture_gate": {
            "status": "INSUFFICIENT_EVIDENCE",
            "checks": [
                {
                    "name": "minimum_fold_count",
                    "status": "PASS",
                    "actual": 6,
                    "threshold": 6,
                    "comparison": "minimum",
                }
            ],
        },
        "derived_metrics": {
            "out_of_sample_total_trades": 12,
            "out_of_sample_total_return_percent": 10.5,
            "out_of_sample_profit_factor": 1.4,
            "out_of_sample_win_rate": 50.0,
            "out_of_sample_max_drawdown_percent": 12.0,
            "out_of_sample_payoff_ratio": 1.8,
        },
        "blocked_by": ["auditable_paper_days"],
        "next_action": "Collect more evidence before making a Phase 2 gate decision.",
    }


def _walk_forward():
    return {
        "validation_status": "VALID",
        "fold_count": 6,
        "validation_contract": {
            "contract_status": "PASS",
            "timeframe_status": "OFFICIAL",
        },
    }


def test_persist_phase2_validation_artifact_writes_json_and_markdown(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.backtesting.phase2_validation_artifacts._outputs_root",
        lambda: Path(tmp_path),
    )

    artifact = persist_phase2_validation_artifact(
        _report(),
        _walk_forward(),
        symbol="DOGEUSDT",
        timeframe="1h",
        signal="LONG",
    )

    json_path = Path(artifact["json_path"])
    markdown_path = Path(artifact["markdown_path"])

    assert json_path.exists()
    assert markdown_path.exists()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["scope"]["symbol"] == "DOGEUSDT"
    assert payload["report"]["overall_status"] == "PARTIAL"
    assert "QuantPulseAI Phase 2 Validation Artifact" in markdown_path.read_text(encoding="utf-8")


def test_persist_phase2_validation_artifact_serializes_trade_datetimes(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.backtesting.phase2_validation_artifacts._outputs_root",
        lambda: Path(tmp_path),
    )
    walk_forward = {
        **_walk_forward(),
        "folds": [
            {
                "out_of_sample": {
                    "trades": [
                        {
                            "entry_time": datetime(2026, 8, 11, 8, 0, 0),
                            "exit_time": datetime(2026, 8, 11, 9, 0, 0),
                        }
                    ]
                }
            }
        ],
    }

    artifact = persist_phase2_validation_artifact(
        _report(),
        walk_forward,
        symbol="XRPUSDT",
        timeframe="1h",
        signal="SHORT",
    )

    payload = json.loads(Path(artifact["json_path"]).read_text(encoding="utf-8"))
    trade = payload["walk_forward_result"]["folds"][0]["out_of_sample"]["trades"][0]
    assert trade["entry_time"] == "2026-08-11T08:00:00"
    assert trade["exit_time"] == "2026-08-11T09:00:00"


def test_phase2_export_requires_completed_async_result(monkeypatch):
    monkeypatch.setattr(
        backtest_api,
        "execute_walk_forward",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("export must not run walk-forward synchronously")
        ),
    )

    try:
        backtest_api.export_phase2_validation_report(
            symbol="DOGEUSDT",
            signal="LONG",
            timeframe="1h",
        )
    except Exception as exc:
        assert exc.status_code == 422
        assert exc.detail["code"] == "COMPLETED_WALK_FORWARD_REQUIRED"
        assert exc.detail["submit_url"] == "/api/backtest/walk-forward/jobs"
    else:
        raise AssertionError("export without an asynchronous result must fail closed")


def test_phase2_export_reuses_completed_async_result_without_recalculation(monkeypatch):
    completed = {
        **_walk_forward(),
        "engine_version": "walk_forward_v1",
        "symbol": "XRPUSDT",
        "timeframe": "1h",
        "signal": "SHORT",
    }
    monkeypatch.setattr(
        backtest_api,
        "execute_walk_forward",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("export must not rerun walk-forward")
        ),
    )
    monkeypatch.setattr(
        backtest_api,
        "build_phase2_validation_report",
        lambda result, **kwargs: _report(),
    )
    monkeypatch.setattr(backtest_api, "_load_paper_measurement", lambda symbol: None)
    monkeypatch.setattr(
        backtest_api,
        "persist_phase2_validation_artifact",
        lambda report, result, **kwargs: {"saved": True},
    )

    payload = backtest_api.export_phase2_validation_report(
        symbol="XRPUSDT",
        signal="SHORT",
        timeframe="1h",
        payload={"result": completed},
    )

    assert payload["calculation_source"] == "COMPLETED_ASYNC_JOB"
    assert payload["artifact"]["saved"] is True


def test_phase2_export_rejects_completed_result_from_another_scope():
    completed = {
        **_walk_forward(),
        "engine_version": "walk_forward_v1",
        "symbol": "BTCUSDT",
        "timeframe": "1h",
        "signal": "LONG",
    }

    try:
        backtest_api.export_phase2_validation_report(
            symbol="XRPUSDT",
            signal="SHORT",
            timeframe="1h",
            payload={"result": completed},
        )
    except Exception as exc:
        assert exc.status_code == 422
        assert "does not match export scope" in exc.detail
    else:
        raise AssertionError("scope mismatch must be rejected")


def test_artifact_history_and_load_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.backtesting.phase2_validation_artifacts._outputs_root",
        lambda: Path(tmp_path),
    )

    first = persist_phase2_validation_artifact(
        _report(),
        _walk_forward(),
        symbol="DOGEUSDT",
        timeframe="1h",
        signal="LONG",
    )
    persist_phase2_validation_artifact(
        _report(),
        _walk_forward(),
        symbol="BTCUSDT",
        timeframe="4h",
        signal="SHORT",
    )

    records = list_phase2_validation_artifacts(symbol="DOGEUSDT", limit=10)
    assert len(records) == 1
    assert records[0]["artifact_id"] == first["artifact_id"]

    loaded = load_phase2_validation_artifact(first["artifact_id"])
    assert loaded["artifact"]["artifact_id"] == first["artifact_id"]
    assert loaded["payload"]["scope"]["symbol"] == "DOGEUSDT"


def test_phase2_history_and_artifact_routes(monkeypatch):
    monkeypatch.setattr(
        backtest_api,
        "list_phase2_validation_artifacts",
        lambda **kwargs: [{"artifact_id": "dogeusdt_1h_long_20260708_120000"}],
    )
    monkeypatch.setattr(
        backtest_api,
        "load_phase2_validation_artifact",
        lambda artifact_id: {"artifact": {"artifact_id": artifact_id}, "payload": {"scope": {"symbol": "DOGEUSDT"}}},
    )

    history = backtest_api.phase2_validation_history(symbol="DOGEUSDT", timeframe="1h", signal="LONG", limit=5)
    artifact = backtest_api.get_phase2_validation_artifact("dogeusdt_1h_long_20260708_120000")

    assert history["source"] == "phase2_validation_history_v1"
    assert history["count"] == 1
    assert artifact["source"] == "phase2_validation_artifact_v1"
    assert artifact["artifact"]["artifact_id"] == "dogeusdt_1h_long_20260708_120000"


def test_outputs_root_uses_runtime_directory_in_shallow_container_layout(
    tmp_path,
    monkeypatch,
):
    runtime_root = tmp_path / "runtime-outputs"
    monkeypatch.setattr(
        phase2_artifacts,
        "__file__",
        "/app/app/backtesting/phase2_validation_artifacts.py",
    )
    monkeypatch.setenv("QUANTPULSE_OUTPUTS_DIR", str(runtime_root))

    assert phase2_artifacts._outputs_root() == runtime_root
    assert phase2_artifacts.list_phase2_validation_artifacts() == []
    assert phase2_artifacts.summarize_phase2_validation_artifacts() == []


def test_phase2_summary_groups_latest_and_previous_by_scope(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.backtesting.phase2_validation_artifacts._outputs_root",
        lambda: Path(tmp_path),
    )

    newer = {
        **_report(),
        "overall_status": "PARTIAL",
        "derived_metrics": {
            **_report()["derived_metrics"],
            "out_of_sample_total_return_percent": 12.0,
            "out_of_sample_profit_factor": 1.6,
        },
    }
    older = {
        **_report(),
        "overall_status": "INSUFFICIENT_EVIDENCE",
        "derived_metrics": {
            **_report()["derived_metrics"],
            "out_of_sample_total_return_percent": 9.0,
            "out_of_sample_profit_factor": 1.2,
        },
    }

    persist_phase2_validation_artifact(
        older,
        _walk_forward(),
        symbol="DOGEUSDT",
        timeframe="1h",
        signal="LONG",
        as_of=__import__("datetime").datetime(2026, 7, 8, 10, 0, 0),
    )
    persist_phase2_validation_artifact(
        newer,
        _walk_forward(),
        symbol="DOGEUSDT",
        timeframe="1h",
        signal="LONG",
        as_of=__import__("datetime").datetime(2026, 7, 8, 11, 0, 0),
    )

    records = summarize_phase2_validation_artifacts(signal="LONG", limit=10)
    assert len(records) == 1
    assert records[0]["sample_count"] == 2
    assert records[0]["status_change"] == "INSUFFICIENT_EVIDENCE_TO_PARTIAL"
    assert records[0]["drift"]["out_of_sample_total_return_percent"] == 3.0
    assert records[0]["drift"]["out_of_sample_profit_factor"] == 0.4


def test_phase2_summary_route_returns_records(monkeypatch):
    monkeypatch.setattr(
        backtest_api,
        "summarize_phase2_validation_artifacts",
        lambda **kwargs: [{"artifact_id": "dogeusdt_1h_long_20260708_110000", "sample_count": 2}],
    )

    payload = backtest_api.phase2_validation_summary(signal="LONG", limit=10)
    assert payload["source"] == "phase2_validation_summary_v1"
    assert payload["count"] == 1
