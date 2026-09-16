import asyncio
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from fastapi.responses import JSONResponse

from app.api.v1 import health_api


def test_dependency_check_reports_active_evidence_storage():
    payload = asyncio.run(health_api.dependency_check())

    assert payload["database_configured"] is True
    assert payload["active_database_scheme"] in {"mssql", "postgresql", "sqlite"}
    assert payload["using_sqlite_fallback"] in {True, False}
    assert payload["evidence_storage"] in {
        "SQL_SERVER",
        "POSTGRESQL",
        "SQLITE_FALLBACK",
    }


def test_evidence_storage_reports_postgresql_canonically():
    postgres_engine = SimpleNamespace(
        url=SimpleNamespace(get_backend_name=lambda: "postgresql")
    )
    with (
        patch.object(health_api, "engine", postgres_engine),
        patch.object(health_api, "USING_SQLITE_FALLBACK", False),
    ):
        assert health_api._evidence_storage() == "POSTGRESQL"


def test_pipeline_health_blocks_paper_execution_on_sqlite_fallback():
    with (
        patch.object(health_api, "USING_SQLITE_FALLBACK", True),
        patch.object(
            health_api,
            "exit_protection_snapshot",
            return_value={"ready": False},
        ),
    ):
        payload = health_api.pipeline_health()

    assert payload["available"] is False
    assert payload["ready"] is False
    assert payload["paper_execution_allowed"] is False
    assert payload["reason"] == "SQLITE_FALLBACK"
    assert payload["exit_protection"]["ready"] is False


@pytest.mark.parametrize(
    ("exit_ready", "execution_allowed", "reason"),
    [
        (True, True, None),
        (False, False, "EXIT_PROTECTION_UNREADY"),
    ],
)
def test_pipeline_health_requires_fast_exit_protection_for_paper_execution(
    exit_ready,
    execution_allowed,
    reason,
):
    db = SimpleNamespace(close=lambda: None)
    pipeline = SimpleNamespace(
        id="pipeline-1",
        generation_id="generation-1",
        status="COMPLETED",
        execution_scope="PAPER_ONLY",
        started_at=None,
        completed_at=None,
        error_category=None,
    )
    repo = SimpleNamespace(
        latest_pipeline=lambda _db: pipeline,
        readiness=lambda *_args: {
            "ready": True,
            "required_stages": ["market"],
            "missing_stages": [],
            "failed_stages": [],
            "jobs": [],
        },
        lineage_counts=lambda *_args: {"MarketFeatures": 1},
    )
    protection = {
        "policy": "FAST_EXIT_HEARTBEAT_V1",
        "ready": exit_ready,
        "status": "READY" if exit_ready else "BLOCKED",
        "reason": None if exit_ready else "Heartbeat is stale",
        "max_age_seconds": 5.0,
        "age_seconds": 0.5 if exit_ready else 8.0,
        "last_attempt_at": None,
        "last_success_at": None,
        "last_worker_status": "OK",
        "last_duration_seconds": 0.1,
        "last_error": None,
        "consecutive_failures": 0,
    }

    with (
        patch.object(health_api, "USING_SQLITE_FALLBACK", False),
        patch.object(health_api, "SessionLocal", return_value=db),
        patch.object(health_api, "PipelineRunRepository", return_value=repo),
        patch.object(
            health_api,
            "exit_protection_snapshot",
            return_value=protection,
        ),
    ):
        payload = health_api.pipeline_health()

    assert payload["ready"] is True
    assert payload["paper_execution_allowed"] is execution_allowed
    assert payload["reason"] == reason
    assert payload["exit_protection"] == protection


def test_running_pipeline_health_skips_contended_lineage_counts():
    db = SimpleNamespace(close=lambda: None)
    pipeline = SimpleNamespace(
        id="pipeline-running",
        generation_id="generation-running",
        status="RUNNING",
        execution_scope="PAPER_ONLY",
        started_at=None,
        completed_at=None,
        error_category=None,
    )
    repo = Mock()
    repo.latest_pipeline.return_value = pipeline
    repo.readiness.return_value = {
        "ready": False,
        "required_stages": ["market"],
        "missing_stages": ["market"],
        "failed_stages": [],
        "jobs": [],
    }
    protection = {
        "ready": True,
        "status": "READY",
    }

    with (
        patch.object(health_api, "USING_SQLITE_FALLBACK", False),
        patch.object(health_api, "SessionLocal", return_value=db),
        patch.object(health_api, "PipelineRunRepository", return_value=repo),
        patch.object(
            health_api,
            "exit_protection_snapshot",
            return_value=protection,
        ),
    ):
        payload = health_api.pipeline_health()

    repo.lineage_counts.assert_not_called()
    assert payload["ready"] is False
    assert payload["reason"] == "PIPELINE_RUNNING"
    assert payload["lineage"]["derived_row_counts"] == {}
    assert payload["lineage"]["verified"] is False


def test_exit_protection_health_is_database_independent():
    protection = {
        "policy": "FAST_EXIT_HEARTBEAT_V1",
        "ready": True,
        "status": "READY",
    }
    with patch.object(
        health_api,
        "exit_protection_snapshot",
        return_value=protection,
    ):
        payload = health_api.exit_protection_health()

    assert payload == protection


def test_liveness_probe_does_not_depend_on_database():
    with patch.object(
        health_api,
        "get_settings",
        return_value=SimpleNamespace(process_role="api"),
    ):
        payload = asyncio.run(health_api.liveness_probe())

    assert payload == {"status": "alive", "process_role": "api"}


def test_readiness_probe_reports_database_ready():
    db = SimpleNamespace(execute=lambda *_args: None, close=lambda: None)
    settings = SimpleNamespace(environment="development", process_role="api")
    with (
        patch.object(health_api, "SessionLocal", return_value=db),
        patch.object(health_api, "get_settings", return_value=settings),
        patch.object(health_api, "USING_SQLITE_FALLBACK", True),
    ):
        payload = health_api.readiness_probe()

    assert payload["status"] == "ready"
    assert payload["evidence_storage"] == "SQLITE_FALLBACK"


def test_readiness_probe_rejects_production_sqlite_fallback():
    db = SimpleNamespace(execute=lambda *_args: None, close=lambda: None)
    settings = SimpleNamespace(environment="production", process_role="api")
    with (
        patch.object(health_api, "SessionLocal", return_value=db),
        patch.object(health_api, "get_settings", return_value=settings),
        patch.object(health_api, "USING_SQLITE_FALLBACK", True),
    ):
        response = health_api.readiness_probe()

    assert isinstance(response, JSONResponse)
    assert response.status_code == 503


def test_readiness_probe_rejects_unavailable_database():
    def unavailable(*_args):
        raise RuntimeError("offline")

    db = SimpleNamespace(execute=unavailable, close=lambda: None)
    settings = SimpleNamespace(environment="production", process_role="api")
    with (
        patch.object(health_api, "SessionLocal", return_value=db),
        patch.object(health_api, "get_settings", return_value=settings),
    ):
        response = health_api.readiness_probe()

    assert isinstance(response, JSONResponse)
    assert response.status_code == 503
