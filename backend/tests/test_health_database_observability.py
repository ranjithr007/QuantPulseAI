import asyncio
from types import SimpleNamespace
from unittest.mock import patch

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
    with patch.object(health_api, "USING_SQLITE_FALLBACK", True):
        payload = health_api.pipeline_health()

    assert payload["available"] is False
    assert payload["ready"] is False
    assert payload["paper_execution_allowed"] is False
    assert payload["reason"] == "SQLITE_FALLBACK"


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
