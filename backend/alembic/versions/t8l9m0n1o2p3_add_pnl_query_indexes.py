"""add indexes for PnL, daily-risk, and time-series evidence queries

Revision ID: t8l9m0n1o2p3
Revises: s7k8l9m0n1o2
"""

from alembic import op
import sqlalchemy as sa


revision = "t8l9m0n1o2p3"
down_revision = "s7k8l9m0n1o2"
branch_labels = None
depends_on = None


INDEXES = (
    (
        "paper_trades",
        "ix_paper_trades_pnl_history",
        ["status", "entry_timeframe", "created_at", "id"],
    ),
    (
        "paper_trades",
        "ix_paper_trades_daily_risk",
        ["status", "closed_at"],
    ),
    (
        "strategy_shadow_trades",
        "ix_strategy_shadow_trades_daily_risk",
        ["status", "closed_at"],
    ),
    (
        "whale_trades",
        "ix_whale_trades_symbol_trade_time",
        ["symbol", "trade_time"],
    ),
    (
        "whale_signals",
        "ix_whale_signals_symbol_created_at",
        ["symbol", "created_at"],
    ),
    (
        "liquidations",
        "ix_liquidations_symbol_event_time",
        ["symbol", "event_time"],
    ),
    (
        "liquidation_heatmaps",
        "ix_liquidation_heatmaps_symbol_created_at",
        ["symbol", "created_at", "id"],
    ),
    (
        "open_interest",
        "ix_open_interest_symbol_timestamp",
        ["symbol", "timestamp", "id"],
    ),
    (
        "futures_mark_prices",
        "ix_futures_mark_prices_latest",
        ["symbol", "timeframe", "is_final", "close_time", "id"],
    ),
    (
        "futures_margin_brackets",
        "ix_futures_margin_brackets_effective",
        ["symbol", "effective_at", "id"],
    ),
    (
        "pipeline_runs",
        "ix_pipeline_runs_retention",
        ["status", "completed_at", "id"],
    ),
)


def _index_names(bind, table_name):
    return {
        item["name"]
        for item in sa.inspect(bind).get_indexes(table_name)
    }


def upgrade():
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    for table_name, name, columns in INDEXES:
        if table_name in tables and name not in _index_names(bind, table_name):
            op.create_index(name, table_name, columns, unique=False)


def downgrade():
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    for table_name, name, _columns in reversed(INDEXES):
        if table_name in tables and name in _index_names(bind, table_name):
            op.drop_index(name, table_name=table_name)
