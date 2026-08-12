"""lower the default paper-entry confidence threshold to 60

Revision ID: pg_20260812_confidence_60
Revises: pg_20260812_wf_jobs
"""

from alembic import op
import sqlalchemy as sa


revision = "pg_20260812_confidence_60"
down_revision = "pg_20260812_wf_jobs"
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
