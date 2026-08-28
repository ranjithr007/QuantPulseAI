"""add concurrent indexes for latest evidence lookups

Revision ID: pg_20260828_usage_indexes
Revises: pg_20260827_notifications
"""

from alembic import op
import sqlalchemy as sa


revision = "pg_20260828_usage_indexes"
down_revision = "pg_20260827_notifications"
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
