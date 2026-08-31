"""add concurrent indexes for strategy summary lookups

Revision ID: pg_20260831_strategy_indexes
Revises: pg_20260828_usage_indexes
"""

from alembic import op
import sqlalchemy as sa


revision = "pg_20260831_strategy_indexes"
down_revision = "pg_20260828_usage_indexes"
branch_labels = None
depends_on = None


INDEXES = (
    (
        "ix_decision_snapshots_strategy_summary",
        "decision_snapshots",
        [
            "strategy_id",
            "strategy_version",
            "decision_version",
            "symbol",
            "created_at",
            "id",
        ],
    ),
    (
        "ix_trade_plans_strategy_summary",
        "trade_plans",
        ["strategy_id", "strategy_version", "created_at"],
    ),
    (
        "ix_risk_decisions_strategy_summary",
        "risk_decisions",
        ["strategy_id", "strategy_version", "created_at"],
    ),
    (
        "ix_paper_trades_strategy_summary",
        "paper_trades",
        ["strategy_id", "strategy_version", "created_at", "id"],
    ),
    (
        "ix_strategy_shadow_trades_strategy_summary",
        "strategy_shadow_trades",
        ["strategy_id", "strategy_version", "created_at", "id"],
    ),
)


def _index_names(bind, table_name):
    return {item["name"] for item in sa.inspect(bind).get_indexes(table_name)}


def upgrade():
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    for name, table, columns in INDEXES:
        if table not in tables or name in _index_names(bind, table):
            continue
        with op.get_context().autocommit_block():
            op.create_index(
                name,
                table,
                columns,
                unique=False,
                postgresql_concurrently=True,
            )


def downgrade():
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    for name, table, _columns in reversed(INDEXES):
        if table not in tables or name not in _index_names(bind, table):
            continue
        with op.get_context().autocommit_block():
            op.drop_index(
                name,
                table_name=table,
                postgresql_concurrently=True,
            )
