import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "n2f3a4b5c6d7_add_strategy_attribution.py"
)


def _migration_module():
    spec = importlib.util.spec_from_file_location("strategy_migration", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_strategy_migration_adds_and_labels_pre_lineage_records(monkeypatch):
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    for table_name in ("trade_plans", "risk_decisions", "paper_trades"):
        sa.Table(
            table_name,
            metadata,
            sa.Column("id", sa.Integer(), primary_key=True),
        )
    sa.Table(
        "decision_snapshots",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("decision_version", sa.String(40), nullable=False),
    )
    metadata.create_all(engine)

    with engine.begin() as connection:
        for table_name in ("trade_plans", "risk_decisions", "paper_trades"):
            connection.execute(sa.text(f"INSERT INTO {table_name} (id) VALUES (1)"))
        connection.execute(
            sa.text(
                "INSERT INTO decision_snapshots (id, decision_version) "
                "VALUES (1, 'phase2_opportunity_ledger_v1'), "
                "(2, 'market_participation_trend_v1')"
            )
        )
        context = MigrationContext.configure(connection)
        operations = Operations(context)
        module = _migration_module()
        monkeypatch.setattr(module, "op", operations)
        module.upgrade()

        for table_name in ("trade_plans", "risk_decisions", "paper_trades"):
            row = connection.execute(
                sa.text(
                    f"SELECT strategy_id, strategy_version, "
                    f"strategy_decision_snapshot_id FROM {table_name}"
                )
            ).mappings().one()
            assert row["strategy_id"] == "LEGACY_UNATTRIBUTED"
            assert row["strategy_version"] == "pre_strategy_lineage_v0"
            assert row["strategy_decision_snapshot_id"] is None

        decisions = connection.execute(
            sa.text(
                "SELECT id, strategy_id, strategy_version "
                "FROM decision_snapshots ORDER BY id"
            )
        ).mappings().all()
        assert all(
            row["strategy_id"] == "LEGACY_UNATTRIBUTED"
            and row["strategy_version"] == "pre_strategy_lineage_v0"
            for row in decisions
        )
