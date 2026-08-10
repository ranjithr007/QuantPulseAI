"""add deterministic pipeline and job run ledger

Revision ID: f1a2b3c4d5e6
Revises: e7b3a914c2d6
Create Date: 2026-07-27 14:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "e7b3a914c2d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.String(length=80), nullable=False),
        sa.Column("generation_id", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("execution_scope", sa.String(length=30), nullable=False),
        sa.Column("source_cutoff", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("error_category", sa.String(length=60), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("generation_id"),
    )
    op.create_index("ix_pipeline_runs_generation_id", "pipeline_runs", ["generation_id"], unique=False)
    op.create_table(
        "pipeline_job_runs",
        sa.Column("id", sa.String(length=80), nullable=False),
        sa.Column("pipeline_run_id", sa.String(length=80), nullable=False),
        sa.Column("job_id", sa.String(length=80), nullable=False),
        sa.Column("idempotency_key", sa.String(length=180), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("input_generation_id", sa.String(length=100), nullable=True),
        sa.Column("output_generation_id", sa.String(length=100), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("rows_read", sa.Integer(), nullable=False),
        sa.Column("rows_written", sa.Integer(), nullable=False),
        sa.Column("error_category", sa.String(length=60), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["pipeline_run_id"], ["pipeline_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_pipeline_job_runs_pipeline_id", "pipeline_job_runs", ["pipeline_run_id"], unique=False)
    op.create_index("ix_pipeline_job_runs_pipeline_job", "pipeline_job_runs", ["pipeline_run_id", "job_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_pipeline_job_runs_pipeline_job", table_name="pipeline_job_runs")
    op.drop_index("ix_pipeline_job_runs_pipeline_id", table_name="pipeline_job_runs")
    op.drop_table("pipeline_job_runs")
    op.drop_index("ix_pipeline_runs_generation_id", table_name="pipeline_runs")
    op.drop_table("pipeline_runs")
