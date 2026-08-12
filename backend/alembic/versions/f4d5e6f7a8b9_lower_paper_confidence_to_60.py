"""lower the default paper-entry confidence threshold to 60

Revision ID: f4d5e6f7a8b9
Revises: e3c4d5e6f7a8
"""

from alembic import op
import sqlalchemy as sa


revision = "f4d5e6f7a8b9"
down_revision = "e3c4d5e6f7a8"
branch_labels = None
depends_on = None


def upgrade():
    settings = sa.table(
        "automation_settings",
        sa.column("id", sa.Integer()),
        sa.column("min_confidence", sa.Float()),
    )
    op.execute(
        settings.update()
        .where(settings.c.id == 1)
        .values(min_confidence=60.0)
    )


def downgrade():
    settings = sa.table(
        "automation_settings",
        sa.column("id", sa.Integer()),
        sa.column("min_confidence", sa.Float()),
    )
    op.execute(
        settings.update()
        .where(settings.c.id == 1)
        .values(min_confidence=70.0)
    )
