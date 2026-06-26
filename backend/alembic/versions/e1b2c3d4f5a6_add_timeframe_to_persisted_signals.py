"""add timeframe to persisted signals

Revision ID: e1b2c3d4f5a6
Revises: ce46732db598
Create Date: 2026-06-24 06:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e1b2c3d4f5a6"
down_revision: Union[str, Sequence[str], None] = "ce46732db598"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("master_signals", sa.Column("timeframe", sa.String(length=10), nullable=True))
    op.create_index(op.f("ix_master_signals_timeframe"), "master_signals", ["timeframe"], unique=False)

    op.add_column("ai_signals", sa.Column("timeframe", sa.String(length=10), nullable=True))
    op.create_index(op.f("ix_ai_signals_timeframe"), "ai_signals", ["timeframe"], unique=False)

    op.execute("UPDATE master_signals SET timeframe = '5m' WHERE timeframe IS NULL")
    op.execute("UPDATE ai_signals SET timeframe = '5m' WHERE timeframe IS NULL")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_ai_signals_timeframe"), table_name="ai_signals")
    op.drop_column("ai_signals", "timeframe")

    op.drop_index(op.f("ix_master_signals_timeframe"), table_name="master_signals")
    op.drop_column("master_signals", "timeframe")
