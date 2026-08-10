from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.database import postgresql_baseline


PROJECT_ROOT = Path(__file__).parents[2]


def test_postgresql_baseline_fingerprint_is_reviewed_and_stable():
    statements = postgresql_baseline.compiled_postgresql_schema()

    assert len(statements) == 125
    assert postgresql_baseline.postgresql_schema_fingerprint() == (
        postgresql_baseline.POSTGRESQL_BASELINE_FINGERPRINT
    )


def test_baseline_refuses_non_postgresql_bind():
    bind = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

    with pytest.raises(RuntimeError, match="only supports PostgreSQL"):
        postgresql_baseline.create_postgresql_baseline(bind)


def test_baseline_create_and_drop_use_locked_metadata():
    bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    with (
        patch.object(postgresql_baseline, "assert_reviewed_postgresql_schema") as check,
        patch.object(postgresql_baseline.Base.metadata, "create_all") as create,
        patch.object(postgresql_baseline.Base.metadata, "drop_all") as drop,
    ):
        postgresql_baseline.create_postgresql_baseline(bind)
        postgresql_baseline.drop_postgresql_baseline(bind)

    assert check.call_count == 2
    create.assert_called_once_with(bind=bind, checkfirst=False)
    drop.assert_called_once_with(bind=bind, checkfirst=True)


def test_cloud_migration_service_uses_postgresql_lineage():
    compose = (PROJECT_ROOT / "docker-compose.cloud.yml").read_text(encoding="utf-8")
    dockerfile = (PROJECT_ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")

    assert '"alembic.postgresql.ini", "upgrade", "head"' in compose
    assert "COPY alembic.postgresql.ini ./alembic.postgresql.ini" in dockerfile
    assert "COPY alembic_postgresql ./alembic_postgresql" in dockerfile


def test_postgresql_lineage_has_single_locked_baseline():
    versions = list(
        (PROJECT_ROOT / "backend" / "alembic_postgresql" / "versions").glob("*.py")
    )

    assert [path.name for path in versions] == ["pg_20260809_baseline.py"]
    content = versions[0].read_text(encoding="utf-8")
    assert 'revision = "pg_20260809_baseline"' in content
    assert "down_revision = None" in content
