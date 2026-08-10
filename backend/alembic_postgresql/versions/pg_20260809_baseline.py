"""Create the reviewed QuantPulseAI PostgreSQL baseline.

Revision ID: pg_20260809_baseline
Revises: None
Create Date: 2026-08-09
"""

from app.database.postgresql_baseline import create_postgresql_baseline
from app.database.postgresql_baseline import drop_postgresql_baseline
from alembic import op


revision = "pg_20260809_baseline"
down_revision = None
branch_labels = ("postgresql",)
depends_on = None


def upgrade():
    create_postgresql_baseline(op.get_bind())


def downgrade():
    drop_postgresql_baseline(op.get_bind())
