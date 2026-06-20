"""Add paper trade tables

Revision ID: b7c9d4f2a6e1
Revises: ce46732db598
Create Date: 2026-06-17 09:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b7c9d4f2a6e1"
down_revision: Union[str, Sequence[str], None] = "ce46732db598"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "paper_trades",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("trade_plan_id", sa.Integer(), nullable=True),
        sa.Column("risk_decision_id", sa.Integer(), nullable=True),
        sa.Column("symbol", sa.String(length=30), nullable=True),
        sa.Column("side", sa.String(length=20), nullable=True),
        sa.Column("entry_price", sa.Float(), nullable=True),
        sa.Column("stop_loss", sa.Float(), nullable=True),
        sa.Column("target1", sa.Float(), nullable=True),
        sa.Column("target2", sa.Float(), nullable=True),
        sa.Column("position_size", sa.Float(), nullable=True),
        sa.Column("risk_reward", sa.Float(), nullable=True),
        sa.Column("risk_percent", sa.Float(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=True),
        sa.Column("exit_price", sa.Float(), nullable=True),
        sa.Column("result", sa.String(length=20), nullable=True),
        sa.Column("pnl_percent", sa.Float(), nullable=True),
        sa.Column("opened_at", sa.DateTime(), nullable=True),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_paper_trades_risk_decision_id"),
        "paper_trades",
        ["risk_decision_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_paper_trades_status"),
        "paper_trades",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_paper_trades_symbol"),
        "paper_trades",
        ["symbol"],
        unique=False,
    )
    op.create_index(
        op.f("ix_paper_trades_trade_plan_id"),
        "paper_trades",
        ["trade_plan_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_paper_trades_trade_plan_id"), table_name="paper_trades")
    op.drop_index(op.f("ix_paper_trades_symbol"), table_name="paper_trades")
    op.drop_index(op.f("ix_paper_trades_status"), table_name="paper_trades")
    op.drop_index(op.f("ix_paper_trades_risk_decision_id"), table_name="paper_trades")
    op.drop_table("paper_trades")
