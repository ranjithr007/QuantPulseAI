"""Add immutable context and cost fields for extended paper measurement.

Revision ID: e8a1c4d7b2f0
Revises: c41b87d2e9f0
Create Date: 2026-06-23 15:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e8a1c4d7b2f0"
down_revision: Union[str, Sequence[str], None] = "c41b87d2e9f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table_name in ("trade_plans", "paper_trades"):
        op.add_column(table_name, sa.Column("mode", sa.String(length=20), nullable=True))
        op.add_column(table_name, sa.Column("entry_timeframe", sa.String(length=10), nullable=True))
        op.add_column(table_name, sa.Column("timeframe_stack", sa.String(length=40), nullable=True))
        op.add_column(table_name, sa.Column("regime", sa.String(length=50), nullable=True))

    op.add_column(
        "paper_trades",
        sa.Column("fee_bps", sa.Float(), nullable=True, server_default="4"),
    )
    op.add_column("paper_trades", sa.Column("fees_percent", sa.Float(), nullable=True))
    op.add_column("paper_trades", sa.Column("gross_pnl_percent", sa.Float(), nullable=True))


def downgrade() -> None:
    for column_name in ("gross_pnl_percent", "fees_percent", "fee_bps"):
        op.drop_column("paper_trades", column_name)

    for table_name in ("paper_trades", "trade_plans"):
        for column_name in ("regime", "timeframe_stack", "entry_timeframe", "mode"):
            op.drop_column(table_name, column_name)
