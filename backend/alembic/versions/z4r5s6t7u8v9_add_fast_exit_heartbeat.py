"""Share the fast-exit worker heartbeat across API and worker processes.

Revision ID: z4r5s6t7u8v9
Revises: y3q4r5s6t7u8
"""

from alembic import op
import sqlalchemy as sa


revision = "z4r5s6t7u8v9"
down_revision = "y3q4r5s6t7u8"
branch_labels = None
depends_on = None


def upgrade():
    if not sa.inspect(op.get_bind()).has_table("fast_exit_heartbeats"):
        op.create_table(
            "fast_exit_heartbeats",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
            sa.Column("last_success_at", sa.DateTime(), nullable=True),
            sa.Column("last_status", sa.String(length=20), nullable=False),
            sa.Column("last_duration_seconds", sa.Float(), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("consecutive_failures", sa.Integer(), nullable=False),
            sa.Column("price_stream_json", sa.Text(), nullable=True),
        )


def downgrade():
    # Keep the operational safety heartbeat on application rollback.
    pass
