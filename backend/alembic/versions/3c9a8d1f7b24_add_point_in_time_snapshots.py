"""Add immutable point-in-time snapshot tables.

Revision ID: 3c9a8d1f7b24
Revises: e8a1c4d7b2f0
Create Date: 2026-06-24 11:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "3c9a8d1f7b24"
down_revision: Union[str, Sequence[str], None] = "e8a1c4d7b2f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "feature_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("timeframe", sa.String(length=10), nullable=False),
        sa.Column("source_timestamp", sa.DateTime(), nullable=False),
        sa.Column("effective_timestamp", sa.DateTime(), nullable=False),
        sa.Column("feature_version", sa.String(length=40), nullable=False),
        sa.Column("quality_state", sa.String(length=20), nullable=False),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "symbol",
            "timeframe",
            "effective_timestamp",
            "feature_version",
            name="uq_feature_snapshots_identity",
        ),
    )
    op.create_index(
        op.f("ix_feature_snapshots_symbol"),
        "feature_snapshots",
        ["symbol"],
        unique=False,
    )
    op.create_index(
        op.f("ix_feature_snapshots_timeframe"),
        "feature_snapshots",
        ["timeframe"],
        unique=False,
    )
    op.create_index(
        op.f("ix_feature_snapshots_effective_timestamp"),
        "feature_snapshots",
        ["effective_timestamp"],
        unique=False,
    )

    op.create_table(
        "decision_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("timeframe", sa.String(length=10), nullable=False),
        sa.Column("source_timestamp", sa.DateTime(), nullable=False),
        sa.Column("effective_timestamp", sa.DateTime(), nullable=False),
        sa.Column("feature_version", sa.String(length=40), nullable=False),
        sa.Column("decision_version", sa.String(length=40), nullable=False),
        sa.Column("quality_state", sa.String(length=20), nullable=False),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("regime", sa.String(length=50), nullable=True),
        sa.Column("thesis_id", sa.String(length=80), nullable=True),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "symbol",
            "timeframe",
            "effective_timestamp",
            "decision_version",
            name="uq_decision_snapshots_identity",
        ),
    )
    op.create_index(
        op.f("ix_decision_snapshots_symbol"),
        "decision_snapshots",
        ["symbol"],
        unique=False,
    )
    op.create_index(
        op.f("ix_decision_snapshots_timeframe"),
        "decision_snapshots",
        ["timeframe"],
        unique=False,
    )
    op.create_index(
        op.f("ix_decision_snapshots_effective_timestamp"),
        "decision_snapshots",
        ["effective_timestamp"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_decision_snapshots_effective_timestamp"),
        table_name="decision_snapshots",
    )
    op.drop_index(op.f("ix_decision_snapshots_timeframe"), table_name="decision_snapshots")
    op.drop_index(op.f("ix_decision_snapshots_symbol"), table_name="decision_snapshots")
    op.drop_table("decision_snapshots")

    op.drop_index(
        op.f("ix_feature_snapshots_effective_timestamp"),
        table_name="feature_snapshots",
    )
    op.drop_index(op.f("ix_feature_snapshots_timeframe"), table_name="feature_snapshots")
    op.drop_index(op.f("ix_feature_snapshots_symbol"), table_name="feature_snapshots")
    op.drop_table("feature_snapshots")
