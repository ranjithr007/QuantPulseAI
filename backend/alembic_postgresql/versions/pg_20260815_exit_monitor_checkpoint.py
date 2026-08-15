"""add paper exit monitor checkpoint

Revision ID: pg_20260815_exit_checkpoint
Revises: pg_20260815_all_staged_exit
"""

from alembic import op
import sqlalchemy as sa


revision = "pg_20260815_exit_checkpoint"
down_revision = "pg_20260815_all_staged_exit"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "paper_trades",
        sa.Column("exit_monitor_timeframe", sa.String(length=10), nullable=True),
    )
    op.add_column(
        "paper_trades",
        sa.Column("last_exit_evaluated_at", sa.DateTime(), nullable=True),
    )
    paper_trades = sa.table(
        "paper_trades",
        sa.column("status", sa.String()),
        sa.column("opened_at", sa.DateTime()),
        sa.column("exit_monitor_timeframe", sa.String()),
        sa.column("last_exit_evaluated_at", sa.DateTime()),
    )
    op.execute(
        paper_trades.update()
        .where(paper_trades.c.status == "OPEN")
        .values(
            exit_monitor_timeframe="5m",
            last_exit_evaluated_at=paper_trades.c.opened_at,
        )
    )


def downgrade():
    op.drop_column("paper_trades", "last_exit_evaluated_at")
    op.drop_column("paper_trades", "exit_monitor_timeframe")
