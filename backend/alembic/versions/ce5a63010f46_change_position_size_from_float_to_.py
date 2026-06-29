"""change position size from float to string

Revision ID: ce5a63010f46
Revises: e690cf9cb47e
Create Date: 2026-06-27 08:28:58.127499

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ce5a63010f46'
down_revision: Union[str, Sequence[str], None] = 'e690cf9cb47e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
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
        existing_nullable=True,
    )
