"""add deterministic generation lineage to derived rows

Revision ID: a7c8d9e0f1b2
Revises: f1a2b3c4d5e6
Create Date: 2026-07-27 16:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7c8d9e0f1b2"
down_revision: Union[str, Sequence[str], None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DERIVED_TABLES = (
    "MarketFeatures",
    "MarketRegimes",
    "MarketOrderFlow",
    "market_smc_signals",
    "fusion_signals",
    "risk_decisions",
    "trade_plans",
    "feature_snapshots",
    "decision_snapshots",
)


def upgrade() -> None:
    for table_name in DERIVED_TABLES:
        op.add_column(
            table_name,
            sa.Column("data_generation_id", sa.String(length=100), nullable=True),
        )


def downgrade() -> None:
    for table_name in reversed(DERIVED_TABLES):
        op.drop_column(table_name, "data_generation_id")
