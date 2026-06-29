"""add position size to master signals

Revision ID: e690cf9cb47e
Revises: 697c8adfb85c
Create Date: 2026-06-27 07:17:04.564402

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "e690cf9cb47e"
down_revision: Union[str, Sequence[str], None] = "697c8adfb85c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    op.add_column(
        "master_signals",
        sa.Column(
            "position_size",
            sa.Numeric(precision=20, scale=8),
            nullable=True,
        ),
    )
    
    op.add_column(
        "master_signals",
        sa.Column(
            "stop_loss",
            sa.Numeric(precision=20, scale=8),
            nullable=True,
        ),
    )
    
    op.add_column(
        "master_signals",
        sa.Column(
            "trade_allowed",
            sa.Numeric(precision=20, scale=8),
            nullable=True,
        ),
    )
    
    op.add_column(
        "master_signals",
        sa.Column(
            "risk_reward",
            sa.Numeric(precision=20, scale=8),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("master_signals", "position_size")
    op.drop_column("master_signals", "stop_loss")
    op.drop_column("master_signals", "trade_allowed")
    op.drop_column("master_signals", "risk_reward")
