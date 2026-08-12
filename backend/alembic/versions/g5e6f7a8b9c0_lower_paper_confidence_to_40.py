"""lower the default paper-entry confidence threshold to 40

Revision ID: g5e6f7a8b9c0
Revises: f4d5e6f7a8b9
"""

from alembic import op
import sqlalchemy as sa


revision = "g5e6f7a8b9c0"
down_revision = "f4d5e6f7a8b9"
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
        .values(min_confidence=40.0)
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
        .values(min_confidence=60.0)
    )
