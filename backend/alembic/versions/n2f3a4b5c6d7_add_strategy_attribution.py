"""add durable strategy attribution

Revision ID: n2f3a4b5c6d7
Revises: m1e2f3a4b5c6
"""

from alembic import op
import sqlalchemy as sa


revision = "n2f3a4b5c6d7"
down_revision = "m1e2f3a4b5c6"
branch_labels = None
depends_on = None

LEGACY_STRATEGY_ID = "LEGACY_UNATTRIBUTED"
LEGACY_STRATEGY_VERSION = "pre_strategy_lineage_v0"


def upgrade():
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    _add_columns(
        bind,
        tables,
        "decision_snapshots",
        (
            sa.Column("strategy_id", sa.String(length=50), nullable=True),
            sa.Column("strategy_version", sa.String(length=50), nullable=True),
        ),
    )
    for table_name in ("trade_plans", "risk_decisions", "paper_trades"):
        _add_columns(
            bind,
            tables,
            table_name,
            (
                sa.Column("strategy_id", sa.String(length=50), nullable=True),
                sa.Column("strategy_version", sa.String(length=50), nullable=True),
                sa.Column(
                    "strategy_decision_snapshot_id",
                    sa.Integer(),
                    nullable=True,
                ),
            ),
        )

    _backfill(tables)
    _add_indexes(bind, tables)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    for table_name in ("paper_trades", "risk_decisions", "trade_plans"):
        if table_name not in tables:
            continue
        indexes = {item["name"] for item in inspector.get_indexes(table_name)}
        for suffix in ("strategy_snapshot", "strategy_version", "strategy_id"):
            index_name = f"ix_{table_name}_{suffix}"
            if index_name in indexes:
                op.drop_index(index_name, table_name=table_name)
        columns = {
            item["name"] for item in sa.inspect(bind).get_columns(table_name)
        }
        for name in (
            "strategy_decision_snapshot_id",
            "strategy_version",
            "strategy_id",
        ):
            if name in columns:
                op.drop_column(table_name, name)

    if "decision_snapshots" in tables:
        indexes = {
            item["name"]
            for item in sa.inspect(bind).get_indexes("decision_snapshots")
        }
        for suffix in ("strategy_version", "strategy_id"):
            index_name = f"ix_decision_snapshots_{suffix}"
            if index_name in indexes:
                op.drop_index(index_name, table_name="decision_snapshots")
        columns = {
            item["name"]
            for item in sa.inspect(bind).get_columns("decision_snapshots")
        }
        for name in ("strategy_version", "strategy_id"):
            if name in columns:
                op.drop_column("decision_snapshots", name)


def _add_columns(bind, tables, table_name, columns):
    if table_name not in tables:
        return
    existing = {
        item["name"] for item in sa.inspect(bind).get_columns(table_name)
    }
    for column in columns:
        if column.name not in existing:
            op.add_column(table_name, column)


def _backfill(tables):
    params = {
        "strategy_id": LEGACY_STRATEGY_ID,
        "strategy_version": LEGACY_STRATEGY_VERSION,
    }
    for table_name in ("trade_plans", "risk_decisions", "paper_trades"):
        if table_name in tables:
            op.execute(
                sa.text(
                    f"UPDATE {table_name} "
                    "SET strategy_id = COALESCE(strategy_id, :strategy_id), "
                    "strategy_version = COALESCE(strategy_version, :strategy_version)"
                ).bindparams(**params)
            )
    if "decision_snapshots" in tables:
        op.execute(
            sa.text(
                "UPDATE decision_snapshots "
                "SET strategy_id = COALESCE(strategy_id, :strategy_id), "
                "strategy_version = COALESCE(strategy_version, :strategy_version) "
                "WHERE strategy_id IS NULL OR strategy_version IS NULL"
            ).bindparams(**params)
        )


def _add_indexes(bind, tables):
    for table_name in (
        "decision_snapshots",
        "trade_plans",
        "risk_decisions",
        "paper_trades",
    ):
        if table_name not in tables:
            continue
        indexes = {
            item["name"] for item in sa.inspect(bind).get_indexes(table_name)
        }
        columns = {
            item["name"] for item in sa.inspect(bind).get_columns(table_name)
        }
        for suffix, column in (
            ("strategy_id", "strategy_id"),
            ("strategy_version", "strategy_version"),
            ("strategy_snapshot", "strategy_decision_snapshot_id"),
        ):
            if column not in columns:
                continue
            index_name = f"ix_{table_name}_{suffix}"
            if index_name not in indexes:
                op.create_index(index_name, table_name, [column])
