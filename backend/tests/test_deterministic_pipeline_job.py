from unittest.mock import patch

from app.jobs.deterministic_pipeline_job import _execution_ready, run_deterministic_pipeline_job


def test_deterministic_cycle_preserves_stage_order():
    calls = []

    def stage(name):
        def run():
            calls.append(name)
            return {"status": "COMPLETED", "rows_written": 1}

        return run

    stages = [(name, stage(name)) for name in ("market", "feature", "regime")]
    with patch("app.jobs.deterministic_pipeline_job.STAGE_ORDER", stages):
        result = run_deterministic_pipeline_job()

    assert result["status"] == "COMPLETED"
    assert calls == ["market", "feature", "regime"]
    assert result["order"] == ["market", "feature", "regime"]


def test_deterministic_cycle_blocks_downstream_after_failure():
    calls = []

    def first():
        calls.append("market")
        return {"status": "FAILED", "error": "collector unavailable"}

    def second():
        calls.append("feature")
        return {"status": "COMPLETED"}

    stages = [("market", first), ("feature", second)]
    with patch("app.jobs.deterministic_pipeline_job.STAGE_ORDER", stages):
        result = run_deterministic_pipeline_job()

    assert result["status"] == "FAILED"
    assert calls == ["market"]
    assert result["results"]["feature"]["status"] == "BLOCKED"


def test_execution_gate_requires_all_upstream_stages_without_errors():
    required = {
        name: {"status": "COMPLETED"}
        for name in ("market", "feature", "regime", "orderflow", "smc", "fusion", "risk")
    }
    assert _execution_ready(required) is True

    failed = dict(required)
    failed["risk"] = {"status": "COMPLETED", "errors": ["risk repository unavailable"]}
    assert _execution_ready(failed) is False

    missing = dict(required)
    del missing["fusion"]
    assert _execution_ready(missing) is False

    malformed = dict(required)
    malformed["smc"] = None
    assert _execution_ready(malformed) is False

    list_results = dict(required)
    list_results["feature"] = [{"symbol": "BTCUSDT", "status": "OK"}]
    list_results["smc"] = [{"symbol": "BTCUSDT"}]
    assert _execution_ready(list_results) is True

    list_failed = dict(list_results)
    list_failed["fusion"] = [{"status": "FAILED", "error": "write failed"}]
    assert _execution_ready(list_failed) is False
