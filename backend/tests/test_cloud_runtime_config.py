from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.config import Settings
from app.database import runtime
from app.database import sqlserver


def test_production_api_role_is_cloud_safe_by_default(monkeypatch):
    monkeypatch.setenv("QUANTPULSE_ENV", "production")
    monkeypatch.setenv("QUANTPULSE_PROCESS_ROLE", "api")
    monkeypatch.setenv("QUANTPULSE_ALLOWED_ORIGINS", "https://dashboard.example.com")
    monkeypatch.delenv("QUANTPULSE_ALLOW_SQLITE_FALLBACK", raising=False)

    settings = Settings()

    assert settings.process_role == "api"
    assert settings.run_scheduler is False
    assert settings.run_live_market is True
    assert settings.allow_sqlite_fallback is False
    assert settings.allowed_origins == ["https://dashboard.example.com"]
    assert settings.rate_limit_enabled is True
    assert settings.rate_limit_per_minute == 120
    assert settings.admin_rate_limit_per_minute == 30


def test_worker_role_owns_scheduler_without_live_listener(monkeypatch):
    monkeypatch.setenv("QUANTPULSE_PROCESS_ROLE", "worker")
    monkeypatch.setenv("QUANTPULSE_START_SCHEDULER", "true")
    monkeypatch.setenv("QUANTPULSE_START_LIVE_MARKET", "true")

    settings = Settings()

    assert settings.run_scheduler is True
    assert settings.run_live_market is False


def test_production_api_requires_strong_admin_key(monkeypatch):
    monkeypatch.setenv("QUANTPULSE_ENV", "production")
    monkeypatch.setenv("QUANTPULSE_PROCESS_ROLE", "api")
    monkeypatch.delenv("QUANTPULSE_ADMIN_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="at least 32 characters"):
        Settings().validate_runtime()


def test_worker_does_not_require_public_api_admin_key(monkeypatch):
    monkeypatch.setenv("QUANTPULSE_ENV", "production")
    monkeypatch.setenv("QUANTPULSE_PROCESS_ROLE", "worker")
    monkeypatch.delenv("QUANTPULSE_ADMIN_API_KEY", raising=False)

    Settings().validate_runtime()


def test_invalid_process_role_is_rejected(monkeypatch):
    monkeypatch.setenv("QUANTPULSE_PROCESS_ROLE", "duplicate-worker")

    with pytest.raises(ValueError, match="QUANTPULSE_PROCESS_ROLE"):
        Settings()


def test_non_positive_rate_limit_is_rejected(monkeypatch):
    monkeypatch.setenv("QUANTPULSE_RATE_LIMIT_PER_MINUTE", "0")

    with pytest.raises(RuntimeError, match="RATE_LIMIT_PER_MINUTE"):
        Settings().validate_runtime()


def test_production_database_failure_does_not_fall_back_to_sqlite():
    settings = SimpleNamespace(allow_sqlite_fallback=False)

    with (
        pytest.raises(RuntimeError, match="SQLite fallback is disabled"),
    ):
        runtime._initialize_engine(
            database_url="mssql+pyodbc://cloud/database",
            settings=settings,
            engine_builder=lambda _url: (_ for _ in ()).throw(
                SQLAlchemyError("database unavailable")
            ),
        )


@pytest.mark.parametrize(
    ("provider_url", "expected"),
    [
        ("postgres://user:pass@host/db", "postgresql+psycopg://user:pass@host/db"),
        ("postgresql://user:pass@host/db", "postgresql+psycopg://user:pass@host/db"),
        (
            "postgresql+psycopg://user:pass@host/db",
            "postgresql+psycopg://user:pass@host/db",
        ),
    ],
)
def test_railway_postgres_urls_select_psycopg3(provider_url, expected):
    assert runtime.normalize_database_url(provider_url) == expected
    assert runtime.database_backend(provider_url) == "postgresql"


def test_legacy_sqlserver_module_reexports_neutral_runtime():
    assert sqlserver.Base is runtime.Base
    assert sqlserver.engine is runtime.engine
    assert sqlserver.SessionLocal is runtime.SessionLocal


def test_database_engine_normalizes_provider_postgres_url_before_creation():
    sentinel = object()
    with patch.object(runtime, "create_engine", return_value=sentinel) as create:
        result = runtime._build_database_engine("postgres://user:pass@host/db")

    assert result is sentinel
    assert create.call_args.args[0] == "postgresql+psycopg://user:pass@host/db"


def test_explicit_sqlite_url_is_not_replaced_by_shared_fallback(tmp_path):
    configured_path = tmp_path / "isolated-acceptance.sqlite"
    settings = SimpleNamespace(allow_sqlite_fallback=True)

    database_engine, using_fallback = runtime._initialize_engine(
        database_url=f"sqlite:///{configured_path.as_posix()}",
        settings=settings,
    )
    try:
        assert using_fallback is True
        assert database_engine.url.database == configured_path.as_posix()
    finally:
        database_engine.dispose()


def test_model_package_does_not_import_windows_only_socket_api():
    from pathlib import Path

    models_init = Path(__file__).parents[1] / "app" / "database" / "models" / "__init__.py"

    assert "from socket import fromshare" not in models_init.read_text(encoding="utf-8")


def test_cloud_compose_separates_api_worker_migration_and_frontend():
    from pathlib import Path

    project_root = Path(__file__).parents[2]
    compose = (project_root / "docker-compose.cloud.yml").read_text(encoding="utf-8")

    for service in ("migrate:", "api:", "worker:", "frontend:"):
        assert service in compose
    assert 'QUANTPULSE_PROCESS_ROLE: worker' in compose
    assert 'command: ["python", "-m", "app.worker"]' in compose
    assert (
        'command: ["alembic", "-c", "alembic.postgresql.ini", "upgrade", "head"]'
        in compose
    )


def test_cloud_images_and_spa_configuration_are_present():
    from pathlib import Path

    project_root = Path(__file__).parents[2]

    assert (project_root / "backend" / "Dockerfile").is_file()
    assert (project_root / "frontend" / "quantpulse-dashboard" / "Dockerfile").is_file()
    nginx = (
        project_root
        / "frontend"
        / "quantpulse-dashboard"
        / "nginx.conf.template"
    ).read_text(encoding="utf-8")
    assert "try_files $uri $uri/ /index.html;" in nginx
    assert "X-Content-Type-Options" in nginx
    assert "X-Frame-Options" in nginx
    assert "Referrer-Policy" in nginx

    requirements = (project_root / "backend" / "requirements.txt").read_text(
        encoding="utf-8"
    )
    assert "psycopg[binary]" in requirements
