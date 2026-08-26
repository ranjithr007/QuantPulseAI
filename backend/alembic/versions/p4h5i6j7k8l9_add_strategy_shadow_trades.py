"""add isolated strategy shadow-trade ledger

Revision ID: p4h5i6j7k8l9
Revises: o3g4h5i6j7k8
"""

from alembic import op
import sqlalchemy as sa


revision = "p4h5i6j7k8l9"
down_revision = "o3g4h5i6j7k8"
branch_labels = None
depends_on = None


TABLE = "strategy_shadow_trades"


def upgrade():
    bind = op.get_bind()
    if TABLE in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("trade_plan_id", sa.Integer(), nullable=False),
        sa.Column("risk_decision_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(30), nullable=False),
        sa.Column("side", sa.String(20), nullable=False),
        sa.Column("strategy_id", sa.String(50), nullable=False),
        sa.Column("strategy_version", sa.String(50), nullable=False),
        sa.Column("strategy_decision_snapshot_id", sa.Integer(), nullable=False),
        sa.Column("entry_price", sa.Float(), nullable=False),
        sa.Column("stop_loss", sa.Float(), nullable=False),
        sa.Column("initial_stop_loss", sa.Float(), nullable=False),
        sa.Column("target1", sa.Float(), nullable=False),
        sa.Column("target2", sa.Float(), nullable=False),
        sa.Column("position_size", sa.Float()),
        sa.Column("position_notional_inr", sa.Float()),
        sa.Column("margin_used_inr", sa.Float()),
        sa.Column("leverage", sa.Float()),
        sa.Column("risk_reward", sa.Float()),
        sa.Column("risk_percent", sa.Float()),
        sa.Column("confidence", sa.Float()),
        sa.Column("entry_timeframe", sa.String(10), nullable=False),
        sa.Column("timeframe_stack", sa.String(40)),
        sa.Column("regime", sa.String(50)),
        sa.Column("exit_policy", sa.String(50)),
        sa.Column("target1_fraction", sa.Float()),
        sa.Column("remaining_position_fraction", sa.Float()),
        sa.Column("max_hold_hours", sa.Integer()),
        sa.Column("target1_hit_at", sa.DateTime()),
        sa.Column("target1_exit_price", sa.Float()),
        sa.Column("partial_realized_pnl_inr", sa.Float()),
        sa.Column("exit_monitor_timeframe", sa.String(10)),
        sa.Column("last_exit_evaluated_at", sa.DateTime()),
        sa.Column("validation_contract_version", sa.String(100)),
        sa.Column("fill_model_version", sa.String(100)),
        sa.Column("planned_entry_price", sa.Float()),
        sa.Column("entry_slippage_percent", sa.Float()),
        sa.Column("exit_slippage_percent", sa.Float()),
        sa.Column("funding_rate_snapshot", sa.Float()),
        sa.Column("funding_event_count", sa.Integer()),
        sa.Column("funding_cost_percent", sa.Float()),
        sa.Column("fee_bps", sa.Float(), server_default="7.5"),
        sa.Column("fees_percent", sa.Float()),
        sa.Column("gross_pnl_percent", sa.Float()),
        sa.Column("realized_pnl_inr", sa.Float()),
        sa.Column("status", sa.String(20), nullable=False, server_default="OPEN"),
        sa.Column("exit_price", sa.Float()),
        sa.Column("exit_reason", sa.String(30)),
        sa.Column("result", sa.String(20)),
        sa.Column("pnl_percent", sa.Float()),
        sa.Column("opened_at", sa.DateTime()),
        sa.Column("closed_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime()),
    )
    for column in (
        "trade_plan_id",
        "risk_decision_id",
        "symbol",
        "strategy_id",
        "strategy_version",
        "strategy_decision_snapshot_id",
        "status",
        "exit_reason",
    ):
        op.create_index(f"ix_{TABLE}_{column}", TABLE, [column])
    op.create_index(
        "uq_shadow_trades_one_open_strategy_symbol",
        TABLE,
        ["strategy_id", "strategy_version", "symbol"],
        unique=True,
        postgresql_where=sa.text("status = 'OPEN'"),
        sqlite_where=sa.text("status = 'OPEN'"),
        mssql_where=sa.text("status = 'OPEN'"),
    )


def downgrade():
    if TABLE in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table(TABLE)
