"""Add durable trade thesis lineage.

Revision ID: 5e7a9d1c8f12
Revises: 4d3e7f2b8c61
Create Date: 2026-06-24 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "5e7a9d1c8f12"
down_revision: Union[str, Sequence[str], None] = "4d3e7f2b8c61"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "trade_theses",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("thesis_key", sa.String(length=100), nullable=False),
        sa.Column("symbol", sa.String(length=30), nullable=False),
        sa.Column("side", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("lifecycle_state", sa.String(length=20), nullable=False),
        sa.Column("lifecycle_reason", sa.String(length=1000), nullable=True),
        sa.Column("source_signal", sa.String(length=20), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("mode", sa.String(length=20), nullable=True),
        sa.Column("entry_timeframe", sa.String(length=10), nullable=True),
        sa.Column("timeframe_stack", sa.String(length=40), nullable=True),
        sa.Column("regime", sa.String(length=50), nullable=True),
        sa.Column("trade_plan_id", sa.Integer(), nullable=True),
        sa.Column("risk_decision_id", sa.Integer(), nullable=True),
        sa.Column("paper_trade_id", sa.Integer(), nullable=True),
        sa.Column("assumptions_json", sa.Text(), nullable=False),
        sa.Column("invalidation_json", sa.Text(), nullable=False),
        sa.Column("targets_json", sa.Text(), nullable=False),
        sa.Column("scenario_json", sa.Text(), nullable=True),
        sa.Column("contradiction_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("invalidated_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_trade_theses_thesis_key", "trade_theses", ["thesis_key"], unique=True)
    op.create_index("ix_trade_theses_symbol", "trade_theses", ["symbol"])
    op.create_index("ix_trade_theses_side", "trade_theses", ["side"])
    op.create_index("ix_trade_theses_lifecycle_state", "trade_theses", ["lifecycle_state"])
    op.create_index("ix_trade_theses_created_at", "trade_theses", ["created_at"])
    op.create_index("ix_trade_theses_updated_at", "trade_theses", ["updated_at"])
    op.create_index("ix_trade_theses_trade_plan_id", "trade_theses", ["trade_plan_id"])
    op.create_index("ix_trade_theses_risk_decision_id", "trade_theses", ["risk_decision_id"])
    op.create_index("ix_trade_theses_paper_trade_id", "trade_theses", ["paper_trade_id"])

    op.add_column("trade_plans", sa.Column("thesis_id", sa.Integer(), nullable=True))
    op.create_index("ix_trade_plans_thesis_id", "trade_plans", ["thesis_id"])
    op.add_column("risk_decisions", sa.Column("thesis_id", sa.Integer(), nullable=True))
    op.create_index("ix_risk_decisions_thesis_id", "risk_decisions", ["thesis_id"])
    op.add_column("paper_trades", sa.Column("thesis_id", sa.Integer(), nullable=True))
    op.create_index("ix_paper_trades_thesis_id", "paper_trades", ["thesis_id"])


def downgrade() -> None:
    for table_name, index_name, column_name in (
        ("paper_trades", "ix_paper_trades_thesis_id", "thesis_id"),
        ("risk_decisions", "ix_risk_decisions_thesis_id", "thesis_id"),
        ("trade_plans", "ix_trade_plans_thesis_id", "thesis_id"),
    ):
        op.drop_index(index_name, table_name=table_name)
        op.drop_column(table_name, column_name)

    for index_name in (
        "ix_trade_theses_paper_trade_id",
        "ix_trade_theses_risk_decision_id",
        "ix_trade_theses_trade_plan_id",
        "ix_trade_theses_updated_at",
        "ix_trade_theses_created_at",
        "ix_trade_theses_lifecycle_state",
        "ix_trade_theses_side",
        "ix_trade_theses_symbol",
        "ix_trade_theses_thesis_key",
    ):
        op.drop_index(index_name, table_name="trade_theses")
    op.drop_table("trade_theses")
