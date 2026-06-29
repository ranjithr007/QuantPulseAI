"""merge timeframe and thesis lineage heads

Revision ID: 697c8adfb85c
Revises: e1b2c3d4f5a6, 5e7a9d1c8f12
Create Date: 2026-06-27 07:02:29.207135

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '697c8adfb85c'
down_revision: Union[str, Sequence[str], None] = ('e1b2c3d4f5a6', '5e7a9d1c8f12')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
