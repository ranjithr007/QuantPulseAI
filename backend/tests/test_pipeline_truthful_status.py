from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.jobs import deterministic_pipeline_job as deterministic
from app.jobs import pipeline_cycle_job as legacy
from app.jobs import watchlist_persist_job as watchlist


@pytest.mark.parametrize("status", ["FAILED", "ERROR", "UNAVAILABLE", "BLOCKED"])
def test_watchlist_returned_failure_is_not_reported_ok(monkeypatch, status):
    monkeypatch.setattr(watchlist, "_invalidate_low_confidence_open_trades", lambda: {})
    monkeypatch.setattr(watchlist, "persist_ready_watchlist_setups_for_stack", lambda **_: {"status": status})
    result = watchlist.run_watchlist_persist_job()
    assert result["status"] == status
    assert result["persistence"]["status"] == status


@pytest.mark.parametrize("result", [
    {"status": "PARTIAL"}, {"status": "DEGRADED"}, {"errors": ["database timeout"]},
    {"failed_symbols": ["BTCUSDT"]}, {"cache": {"stale_symbols": ["BTCUSDT"]}},
])
def test_watchlist_partial_evidence_is_degraded_not_success(result):
    assert watchlist._persistence_status(result) == "DEGRADED"


def test_normal_watchlist_wait_is_not_infrastructure_failure():
    assert watchlist._persistence_status({"saved_count": 0, "skipped": [{"decision": "WAIT"}]}) == "OK"
    assert watchlist._persistence_status(None) == "FAILED"


@pytest.mark.parametrize("status", ["FAILED", "ERROR", "UNAVAILABLE", "BLOCKED", "PARTIAL", "", "PENDING"])
@pytest.mark.parametrize("required_stage", ["paper_trade_monitor", "risk"])
def test_required_evidence_status_cannot_be_treated_as_ready(status, required_stage):
    results = {"paper_trade_monitor": {"status": "OK"}, "risk": {"status": "COMPLETED"}}
    results[required_stage] = {"status": status}
    assert not deterministic._execution_ready(results)


def test_risk_local_degradation_remains_eligible_but_monitor_degradation_does_not():
    assert deterministic._execution_ready({
        "paper_trade_monitor": {"status": "OK"},
        "risk": {"status": "DEGRADED", "errors": ["BTC plan missing"], "trade_plans": {"approved": 1}},
    })
    assert not deterministic._execution_ready({"paper_trade_monitor": {"status": "DEGRADED"}, "risk": {"status": "OK"}})
    assert not deterministic._execution_ready({"paper_trade_monitor": {"status": "OK"}, "risk": [None]})


@pytest.mark.parametrize("status", ["ERROR", "UNAVAILABLE", "BLOCKED"])
def test_deterministic_optional_failures_record_degradation_and_keep_independent_execution(monkeypatch, status):
    execute = Mock(return_value={"status": "OK"})
    monkeypatch.setattr(deterministic, "USING_SQLITE_FALLBACK", True)
    monkeypatch.setattr(deterministic, "STAGE_ORDER", [
        ("paper_trade_monitor", lambda: {"status": "OK"}),
        ("watchlist_persist", lambda: {"status": status}),
        ("risk", lambda: {"status": "OK"}),
        ("paper_trade_execute", execute),
    ])
    result = deterministic.run_deterministic_pipeline_job()
    assert result["status"] == "DEGRADED"
    assert result["degraded_stages"] == ["watchlist_persist"]
    assert result["results"]["watchlist_persist"]["result"]["status"] == status
    execute.assert_called_once()


def _stub_legacy_jobs(monkeypatch, risk_status="OK", watchlist_status="OK"):
    monkeypatch.setattr(legacy, "USING_SQLITE_FALLBACK", True)
    monkeypatch.setattr(legacy, "run_paper_trade_monitor_job", lambda: {"status": "OK"})
    monkeypatch.setattr(legacy, "run_watchlist_persist_job", lambda: {"status": watchlist_status})
    monkeypatch.setattr(legacy, "run_risk_job", lambda: {"status": risk_status})
    execute = Mock(return_value={"status": "OK"})
    monkeypatch.setattr(legacy, "run_paper_trade_execute_job", execute)
    return execute


@pytest.mark.parametrize("status", ["FAILED", "ERROR", "UNAVAILABLE", "BLOCKED"])
def test_legacy_executor_is_blocked_if_risk_job_returned_failure(monkeypatch, status):
    execute = _stub_legacy_jobs(monkeypatch, risk_status=status)
    result = legacy.run_pipeline_cycle_job()
    assert result["status"] == "PARTIAL"
    assert result["results"]["paper_trade_execute"]["status"] == "BLOCKED"
    execute.assert_not_called()


def test_legacy_optional_failure_does_not_block_executor_and_ledger_records_failure(monkeypatch):
    execute = _stub_legacy_jobs(monkeypatch, watchlist_status="UNAVAILABLE")
    monkeypatch.setattr(legacy, "USING_SQLITE_FALLBACK", False)
    db = Mock()
    monkeypatch.setattr(legacy, "SessionLocal", lambda: db)
    ledger = Mock()
    ledger.recover_stale_running.return_value = {"recovered_jobs": 0}
    ledger.start_pipeline.return_value = (SimpleNamespace(id=1), True)
    ledger.start_job.side_effect = [(SimpleNamespace(id=i), True) for i in range(10, 14)]
    monkeypatch.setattr(legacy, "PipelineRunRepository", lambda: ledger)
    result = legacy.run_pipeline_cycle_job()
    assert result["status"] == "PARTIAL"
    execute.assert_called_once()
    statuses = {call.args[1]: call.kwargs["status"] for call in ledger.finish_job.call_args_list}
    assert statuses == {10: "COMPLETED", 11: "FAILED", 12: "COMPLETED", 13: "COMPLETED"}
    db.close.assert_called_once()


def test_legacy_degraded_risk_remains_independent_and_reports_degraded(monkeypatch):
    execute = _stub_legacy_jobs(monkeypatch, risk_status="DEGRADED")
    result = legacy.run_pipeline_cycle_job()
    assert result["status"] == "DEGRADED"
    execute.assert_called_once()


def test_partial_deterministic_stage_marks_whole_run_degraded(monkeypatch):
    monkeypatch.setattr(deterministic, "USING_SQLITE_FALLBACK", True)
    monkeypatch.setattr(deterministic, "STAGE_ORDER", [("watchlist_persist", lambda: {"status": "DEGRADED"})])
    result = deterministic.run_deterministic_pipeline_job()
    assert result["status"] == "DEGRADED"
    assert result["results"]["watchlist_persist"]["status"] == "DEGRADED"


def test_legacy_unknown_return_shapes_do_not_crash_status_report():
    assert legacy._pipeline_cycle_status({"risk": [{"status": "ERROR"}], "monitor": {"status": "OK"}}) == "PARTIAL"
    assert legacy._pipeline_cycle_status({}) == "FAILED"
