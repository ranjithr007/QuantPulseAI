"""add BTC 1h staged paper exit policy state

Revision ID: h6f7a8b9c0d1
Revises: g5e6f7a8b9c0
"""

from alembic import op
import sqlalchemy as sa


revision = "h6f7a8b9c0d1"
down_revision = "g5e6f7a8b9c0"
branch_labels = None
depends_on = None


def upgrade():
    _add_missing("trade_plans", sa.Column("exit_policy", sa.String(50), nullable=True))
    _add_missing("trade_plans", sa.Column("target1_fraction", sa.Float(), nullable=True))
    _add_missing("trade_plans", sa.Column("max_hold_hours", sa.Integer(), nullable=True))
    _add_missing("paper_trades", sa.Column("exit_policy", sa.String(50), nullable=True))
    _add_missing("paper_trades", sa.Column("initial_stop_loss", sa.Float(), nullable=True))
    _add_missing("paper_trades", sa.Column("target1_fraction", sa.Float(), nullable=True))
    _add_missing("paper_trades", sa.Column("remaining_position_fraction", sa.Float(), nullable=True))
    _add_missing("paper_trades", sa.Column("max_hold_hours", sa.Integer(), nullable=True))
    _add_missing("paper_trades", sa.Column("target1_hit_at", sa.DateTime(), nullable=True))
    _add_missing("paper_trades", sa.Column("target1_exit_price", sa.Float(), nullable=True))


def downgrade():
    for column in (
        "target1_exit_price",
        "target1_hit_at",
        "max_hold_hours",
        "remaining_position_fraction",
        "target1_fraction",
        "initial_stop_loss",
        "exit_policy",
    ):
        op.drop_column("paper_trades", column)
    for column in ("max_hold_hours", "target1_fraction", "exit_policy"):
        op.drop_column("trade_plans", column)


def _add_missing(table, column):
    existing = {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}
    if column.name not in existing:
        op.add_column(table, column)
