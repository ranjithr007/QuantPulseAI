"""restore position size and fix trade allowed datatype

Revision ID: cf39f6041cc2
Revises: ce5a63010f46
Create Date: 2026-06-27 08:33:36.635219

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cf39f6041cc2'
down_revision: Union[str, Sequence[str], None] = 'ce5a63010f46'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Reverse the incorrect position_size change
    op.alter_column(
        "master_signals",
        "position_size",
        existing_type=sa.String(length=50),
        type_=sa.Float(),
        existing_nullable=True,
    )

    # Change trade_allowed to Boolean/BIT
    op.alter_column(
        "master_signals",
        "trade_allowed",
        existing_type=sa.Float(),
        type_=sa.String(length=50),
        existing_nullable=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        "master_signals",
        "trade_allowed",
        existing_type=sa.String(length=50),
        type_=sa.Float(),
        existing_nullable=False,
    )

    op.alter_column(
        "master_signals",
        "position_size",
        existing_type=sa.Float(),
        type_=sa.String(length=50),
        existing_nullable=True,
    )
