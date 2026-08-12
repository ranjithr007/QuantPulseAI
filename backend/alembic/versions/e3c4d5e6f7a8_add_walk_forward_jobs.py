"""add durable walk-forward jobs

Revision ID: e3c4d5e6f7a8
Revises: d2b3c4d5e6f7
"""

from alembic import op
import sqlalchemy as sa


revision = "e3c4d5e6f7a8"
down_revision = "d2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "walk_forward_jobs",
        sa.Column("job_id", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("parameters_json", sa.Text(), nullable=False),
        sa.Column("response_json", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("job_id"),
    )
    op.create_index(
        "ix_walk_forward_jobs_status",
        "walk_forward_jobs",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_walk_forward_jobs_created_at",
        "walk_forward_jobs",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_walk_forward_jobs_status_created",
        "walk_forward_jobs",
        ["status", "created_at"],
        unique=False,
    )


def downgrade():
    op.drop_index("ix_walk_forward_jobs_status_created", table_name="walk_forward_jobs")
    op.drop_index("ix_walk_forward_jobs_created_at", table_name="walk_forward_jobs")
    op.drop_index("ix_walk_forward_jobs_status", table_name="walk_forward_jobs")
    op.drop_table("walk_forward_jobs")

