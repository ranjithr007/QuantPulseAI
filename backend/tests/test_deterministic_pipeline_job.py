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


def test_deterministic_cycle_blocks_execution_after_risk_failure():
    calls = []

    def monitor():
        calls.append("paper_trade_monitor")
        return {"status": "COMPLETED"}

    def risk():
        calls.append("risk")
        return {"status": "FAILED", "error": "risk repository unavailable"}

    def execute():
        calls.append("paper_trade_execute")
        return {"status": "COMPLETED"}

    stages = [
        ("paper_trade_monitor", monitor),
        ("risk", risk),
        ("paper_trade_execute", execute),
    ]
    with patch("app.jobs.deterministic_pipeline_job.STAGE_ORDER", stages):
        result = run_deterministic_pipeline_job()

    assert result["status"] == "FAILED"
    assert calls == ["paper_trade_monitor", "risk"]
    assert result["results"]["paper_trade_execute"]["status"] == "BLOCKED"


def test_market_failure_degrades_pipeline_without_blocking_independent_engines():
    calls = []

    def market():
        calls.append("market")
        return {"status": "FAILED", "error": "collector unavailable"}

    def monitor():
        calls.append("paper_trade_monitor")
        return {"status": "COMPLETED", "closed": 1}

    def feature():
        calls.append("feature")
        return {"status": "COMPLETED"}

    stages = [
        ("market", market),
        ("paper_trade_monitor", monitor),
        ("feature", feature),
    ]
    with patch("app.jobs.deterministic_pipeline_job.STAGE_ORDER", stages):
        result = run_deterministic_pipeline_job()

    assert result["status"] == "DEGRADED"
    assert result["degraded_stages"] == ["market"]
    assert calls == ["market", "paper_trade_monitor", "feature"]
    assert result["results"]["paper_trade_monitor"]["status"] == "COMPLETED"
    assert result["results"]["feature"]["status"] == "COMPLETED"


def test_exit_monitor_failure_remains_a_global_hard_gate():
    calls = []

    def monitor():
        calls.append("paper_trade_monitor")
        return {"status": "FAILED", "error": "position monitoring unavailable"}

    def feature():
        calls.append("feature")
        return {"status": "COMPLETED"}

    def risk():
        calls.append("risk")
        return {"status": "COMPLETED"}

    stages = [
        ("paper_trade_monitor", monitor),
        ("feature", feature),
        ("risk", risk),
    ]
    with patch("app.jobs.deterministic_pipeline_job.STAGE_ORDER", stages):
        result = run_deterministic_pipeline_job()

    assert result["status"] == "FAILED"
    assert calls == ["paper_trade_monitor"]
    assert result["results"]["feature"]["status"] == "BLOCKED"
    assert result["results"]["risk"]["status"] == "BLOCKED"


def test_opportunity_recovery_runs_after_upstream_failure():
    calls = []

    def failed_watchlist():
        calls.append("watchlist_persist")
        return {"status": "FAILED", "error": "persistence unavailable"}

    def recovery():
        calls.append("opportunity_coverage_recovery")
        return {"status": "OK", "persisted_count": 6}

    def risk():
        calls.append("risk")
        return {"status": "OK"}

    stages = [
        ("watchlist_persist", failed_watchlist),
        ("opportunity_coverage_recovery", recovery),
        ("risk", risk),
    ]
    with patch("app.jobs.deterministic_pipeline_job.STAGE_ORDER", stages):
        result = run_deterministic_pipeline_job()

    assert result["status"] == "DEGRADED"
    assert calls == ["watchlist_persist", "opportunity_coverage_recovery", "risk"]
    assert result["results"]["risk"]["status"] == "OK"


def test_optional_market_participation_failure_does_not_block_core_signal_path():
    calls = []

    def market_participation():
        calls.append("market_participation_trend")
        return {"status": "FAILED", "error": "spot evidence unavailable"}

    def watchlist():
        calls.append("watchlist_persist")
        return {"status": "OK", "saved_count": 1}

    def risk():
        calls.append("risk")
        return {"status": "OK", "approved": 1}

    stages = [
        ("market_participation_trend", market_participation),
        ("watchlist_persist", watchlist),
        ("risk", risk),
    ]
    with patch("app.jobs.deterministic_pipeline_job.STAGE_ORDER", stages):
        result = run_deterministic_pipeline_job()

    assert result["status"] == "DEGRADED"
    assert result["degraded_stages"] == ["market_participation_trend"]
    assert calls == ["market_participation_trend", "watchlist_persist", "risk"]
    assert result["results"]["market_participation_trend"]["blocking"] is False
    assert result["results"]["watchlist_persist"]["status"] == "OK"
    assert result["results"]["risk"]["status"] == "OK"


def test_optional_market_participation_exception_does_not_block_core_signal_path():
    calls = []

    def market_participation():
        calls.append("market_participation_trend")
        raise RuntimeError("spot collector crashed")

    def watchlist():
        calls.append("watchlist_persist")
        return {"status": "OK", "saved_count": 1}

    stages = [
        ("market_participation_trend", market_participation),
        ("watchlist_persist", watchlist),
    ]
    with patch("app.jobs.deterministic_pipeline_job.STAGE_ORDER", stages):
        result = run_deterministic_pipeline_job()

    assert result["status"] == "DEGRADED"
    assert result["degraded_stages"] == ["market_participation_trend"]
    assert calls == ["market_participation_trend", "watchlist_persist"]
    assert result["results"]["market_participation_trend"]["blocking"] is False


def test_execution_gate_requires_monitor_and_risk_without_errors():
    required = {
        name: {"status": "COMPLETED"}
        for name in ("paper_trade_monitor", "risk")
    }
    assert _execution_ready(required) is True

    failed = dict(required)
    failed["risk"] = {"status": "COMPLETED", "errors": ["risk repository unavailable"]}
    assert _execution_ready(failed) is False

    missing = dict(required)
    del missing["paper_trade_monitor"]
    assert _execution_ready(missing) is False

    malformed = dict(required)
    malformed["paper_trade_monitor"] = None
    assert _execution_ready(malformed) is False

    list_results = dict(required)
    list_results["risk"] = [{"symbol": "BTCUSDT", "status": "OK"}]
    assert _execution_ready(list_results) is True

    list_failed = dict(list_results)
    list_failed["risk"] = [{"status": "FAILED", "error": "write failed"}]
    assert _execution_ready(list_failed) is False


def test_one_strategy_engine_failure_does_not_block_risk_or_executor():
    calls = []

    def stage(name, result):
        def run():
            calls.append(name)
            return result

        return run

    stages = [
        (
            "paper_trade_monitor",
            stage("paper_trade_monitor", {"status": "COMPLETED"}),
        ),
        (
            "feature",
            stage("feature", {"status": "FAILED", "errors": ["bad feature"]}),
        ),
        ("orderflow", stage("orderflow", {"status": "COMPLETED"})),
        ("risk", stage("risk", {"status": "COMPLETED", "errors": []})),
        (
            "paper_trade_execute",
            stage("paper_trade_execute", {"status": "COMPLETED", "executed": 1}),
        ),
    ]

    with patch("app.jobs.deterministic_pipeline_job.STAGE_ORDER", stages):
        result = run_deterministic_pipeline_job()

    assert result["status"] == "DEGRADED"
    assert result["degraded_stages"] == ["feature"]
    assert calls == [
        "paper_trade_monitor",
        "feature",
        "orderflow",
        "risk",
        "paper_trade_execute",
    ]
    assert result["results"]["feature"]["blocking"] is False
    assert result["results"]["paper_trade_execute"]["executed"] == 1
