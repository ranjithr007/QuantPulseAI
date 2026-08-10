"""add paper trade funding accrual

Revision ID: d1a2b3c4d5e6
Revises: d0f1a2b3c4d5
"""

from alembic import op
import sqlalchemy as sa


revision = "d1a2b3c4d5e6"
down_revision = "d0f1a2b3c4d5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "paper_trades",
        sa.Column("funding_event_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "paper_trades",
        sa.Column("funding_cost_percent", sa.Float(), nullable=True),
    )


def downgrade():
    op.drop_column("paper_trades", "funding_cost_percent")
    op.drop_column("paper_trades", "funding_event_count")
