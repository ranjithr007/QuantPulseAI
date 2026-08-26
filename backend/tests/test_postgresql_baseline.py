from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.database import postgresql_baseline


PROJECT_ROOT = Path(__file__).parents[2]


def test_postgresql_baseline_fingerprint_is_reviewed_and_stable():
    statements = postgresql_baseline.compiled_postgresql_schema()

    assert len(statements) == 144
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
    baseline_tables = postgresql_baseline._baseline_tables()
    create.assert_called_once_with(bind=bind, tables=baseline_tables, checkfirst=False)
    drop.assert_called_once_with(bind=bind, tables=baseline_tables, checkfirst=True)
    assert "walk_forward_jobs" not in {table.name for table in baseline_tables}


def test_cloud_migration_service_uses_postgresql_lineage():
    compose = (PROJECT_ROOT / "docker-compose.cloud.yml").read_text(encoding="utf-8")
    dockerfile = (PROJECT_ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")

    assert '"alembic.postgresql.ini", "upgrade", "head"' in compose
    assert "COPY alembic.postgresql.ini ./alembic.postgresql.ini" in dockerfile
    assert "COPY alembic_postgresql ./alembic_postgresql" in dockerfile


def test_postgresql_lineage_has_locked_baseline_and_forward_migrations():
    versions = list(
        (PROJECT_ROOT / "backend" / "alembic_postgresql" / "versions").glob("*.py")
    )

    assert sorted(path.name for path in versions) == [
        "pg_20260809_baseline.py",
        "pg_20260811_one_open_paper_trade_per_symbol.py",
        "pg_20260812_confidence_40.py",
        "pg_20260812_confidence_60.py",
        "pg_20260812_walk_forward_jobs.py",
        "pg_20260815_all_staged_exit.py",
        "pg_20260815_btc_1h_staged_exit.py",
        "pg_20260815_exit_monitor_checkpoint.py",
        "pg_20260815_inr_wallet_ledger.py",
        "pg_20260819_paper_trade_exit_reason.py",
        "pg_20260823_backtest_market_evidence.py",
        "pg_20260826_strategy_attribution.py",
    ]
    content = (PROJECT_ROOT / "backend" / "alembic_postgresql" / "versions" / "pg_20260809_baseline.py").read_text(encoding="utf-8")
    assert 'revision = "pg_20260809_baseline"' in content
    assert "down_revision = None" in content

    invariant = (PROJECT_ROOT / "backend" / "alembic_postgresql" / "versions" / "pg_20260811_one_open_paper_trade_per_symbol.py").read_text(encoding="utf-8")
    assert 'down_revision = "pg_20260809_baseline"' in invariant
    assert "uq_paper_trades_one_open_symbol" in invariant

    jobs = (PROJECT_ROOT / "backend" / "alembic_postgresql" / "versions" / "pg_20260812_walk_forward_jobs.py").read_text(encoding="utf-8")
    assert 'down_revision = "pg_20260811_one_open_symbol"' in jobs
    assert "walk_forward_jobs" in jobs

    confidence = (PROJECT_ROOT / "backend" / "alembic_postgresql" / "versions" / "pg_20260812_confidence_60.py").read_text(encoding="utf-8")
    assert 'down_revision = "pg_20260812_wf_jobs"' in confidence
    assert ".where(settings.c.id == 1)" in confidence
    assert ".values(min_confidence=60.0)" in confidence

    confidence_40 = (PROJECT_ROOT / "backend" / "alembic_postgresql" / "versions" / "pg_20260812_confidence_40.py").read_text(encoding="utf-8")
    assert 'down_revision = "pg_20260812_confidence_60"' in confidence_40
    assert ".where(settings.c.id == 1)" in confidence_40
    assert ".values(min_confidence=40.0)" in confidence_40

    staged_exit = (PROJECT_ROOT / "backend" / "alembic_postgresql" / "versions" / "pg_20260815_btc_1h_staged_exit.py").read_text(encoding="utf-8")
    assert 'down_revision = "pg_20260812_confidence_40"' in staged_exit
    assert '"target1_hit_at"' in staged_exit
    assert '"remaining_position_fraction"' in staged_exit

    all_staged_exit = (PROJECT_ROOT / "backend" / "alembic_postgresql" / "versions" / "pg_20260815_all_staged_exit.py").read_text(encoding="utf-8")
    assert 'down_revision = "pg_20260815_btc_1h_exit"' in all_staged_exit
    assert 'POLICY = "PAPER_STAGED_EXIT_V1"' in all_staged_exit
    assert 'TIMEFRAMES = ("1h", "2h", "4h", "1d")' in all_staged_exit
    assert 'result="STALE_EXIT_POLICY"' in all_staged_exit

    exit_checkpoint = (PROJECT_ROOT / "backend" / "alembic_postgresql" / "versions" / "pg_20260815_exit_monitor_checkpoint.py").read_text(encoding="utf-8")
    assert 'down_revision = "pg_20260815_all_staged_exit"' in exit_checkpoint
    assert '"exit_monitor_timeframe"' in exit_checkpoint
    assert '"last_exit_evaluated_at"' in exit_checkpoint

    wallet_ledger = (PROJECT_ROOT / "backend" / "alembic_postgresql" / "versions" / "pg_20260815_inr_wallet_ledger.py").read_text(encoding="utf-8")
    assert 'down_revision = "pg_20260815_exit_checkpoint"' in wallet_ledger
    assert 'revision = "pg_20260815_wallet_ledger"' in wallet_ledger

    exit_reason = (PROJECT_ROOT / "backend" / "alembic_postgresql" / "versions" / "pg_20260819_paper_trade_exit_reason.py").read_text(encoding="utf-8")
    assert 'down_revision = "pg_20260815_wallet_ledger"' in exit_reason
    assert 'revision = "pg_20260819_stop_reason"' in exit_reason

    evidence = (PROJECT_ROOT / "backend" / "alembic_postgresql" / "versions" / "pg_20260823_backtest_market_evidence.py").read_text(encoding="utf-8")
    assert 'down_revision = "pg_20260819_stop_reason"' in evidence
    assert 'revision = "pg_20260823_evidence"' in evidence

    strategy = (PROJECT_ROOT / "backend" / "alembic_postgresql" / "versions" / "pg_20260826_strategy_attribution.py").read_text(encoding="utf-8")
    assert 'down_revision = "pg_20260823_evidence"' in strategy
    assert 'revision = "pg_20260826_strategy"' in strategy
