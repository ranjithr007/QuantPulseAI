"""add composite indexes for latest evidence lookups

Revision ID: r6j7k8l9m0n1
Revises: q5i6j7k8l9m0
"""

from alembic import op
import sqlalchemy as sa


revision = "r6j7k8l9m0n1"
down_revision = "q5i6j7k8l9m0"
branch_labels = None
depends_on = None


INDEXES = (
    (
        "ix_market_features_symbol_timeframe_created",
        "MarketFeatures",
        ["Symbol", "Timeframe", "CreatedAt", "Id"],
    ),
    (
        "ix_market_regimes_symbol_timeframe_created",
        "MarketRegimes",
        ["Symbol", "Timeframe", "CreatedAt", "Id"],
    ),
    (
        "ix_market_order_flow_symbol_timeframe_created",
        "MarketOrderFlow",
        ["Symbol", "Timeframe", "CreatedAt", "Id"],
    ),
    (
        "ix_market_smc_symbol_timeframe_created",
        "market_smc_signals",
        ["symbol", "timeframe", "created_at", "id"],
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
