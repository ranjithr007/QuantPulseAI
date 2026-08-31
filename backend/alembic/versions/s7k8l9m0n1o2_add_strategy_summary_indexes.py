"""add composite indexes for strategy summary lookups

Revision ID: s7k8l9m0n1o2
Revises: r6j7k8l9m0n1
"""

from alembic import op
import sqlalchemy as sa


revision = "s7k8l9m0n1o2"
down_revision = "r6j7k8l9m0n1"
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
        if table in tables and name not in _index_names(bind, table):
            op.create_index(name, table, columns, unique=False)


def downgrade():
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    for name, table, _columns in reversed(INDEXES):
        if table in tables and name in _index_names(bind, table):
            op.drop_index(name, table_name=table)
