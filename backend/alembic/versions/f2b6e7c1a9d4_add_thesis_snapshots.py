"""Add thesis lifecycle snapshots.

Revision ID: f2b6e7c1a9d4
Revises: 3c9a8d1f7b24
Create Date: 2026-06-24 12:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f2b6e7c1a9d4"
down_revision: Union[str, Sequence[str], None] = "3c9a8d1f7b24"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "thesis_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("thesis_id", sa.Integer(), nullable=False),
        sa.Column("thesis_key", sa.String(length=100), nullable=False),
        sa.Column("symbol", sa.String(length=30), nullable=False),
        sa.Column("side", sa.String(length=20), nullable=False),
        sa.Column("lifecycle_state", sa.String(length=20), nullable=False),
        sa.Column("source_timestamp", sa.DateTime(), nullable=False),
        sa.Column("effective_timestamp", sa.DateTime(), nullable=False),
        sa.Column("snapshot_version", sa.String(length=40), nullable=False),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "thesis_id",
            "effective_timestamp",
            "snapshot_version",
            name="uq_thesis_snapshots_identity",
        ),
    )
    op.create_index(op.f("ix_thesis_snapshots_thesis_id"), "thesis_snapshots", ["thesis_id"], unique=False)
    op.create_index(op.f("ix_thesis_snapshots_thesis_key"), "thesis_snapshots", ["thesis_key"], unique=False)
    op.create_index(op.f("ix_thesis_snapshots_symbol"), "thesis_snapshots", ["symbol"], unique=False)
    op.create_index(op.f("ix_thesis_snapshots_side"), "thesis_snapshots", ["side"], unique=False)
    op.create_index(op.f("ix_thesis_snapshots_lifecycle_state"), "thesis_snapshots", ["lifecycle_state"], unique=False)
    op.create_index(
        op.f("ix_thesis_snapshots_effective_timestamp"),
        "thesis_snapshots",
        ["effective_timestamp"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_thesis_snapshots_effective_timestamp"),
        table_name="thesis_snapshots",
    )
    op.drop_index(op.f("ix_thesis_snapshots_lifecycle_state"), table_name="thesis_snapshots")
    op.drop_index(op.f("ix_thesis_snapshots_side"), table_name="thesis_snapshots")
    op.drop_index(op.f("ix_thesis_snapshots_symbol"), table_name="thesis_snapshots")
    op.drop_index(op.f("ix_thesis_snapshots_thesis_key"), table_name="thesis_snapshots")
    op.drop_index(op.f("ix_thesis_snapshots_thesis_id"), table_name="thesis_snapshots")
    op.drop_table("thesis_snapshots")
