"""Add durable data-quality event ledger.

Revision ID: 4d3e7f2b8c61
Revises: 3c9a8d1f7b24
Create Date: 2026-06-24 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "4d3e7f2b8c61"
down_revision: Union[str, Sequence[str], None] = "3c9a8d1f7b24"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "data_quality_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("timeframe", sa.String(length=10), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("blocked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reason", sa.String(length=1000), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("effective_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_data_quality_events_symbol_timeframe_created_at",
        "data_quality_events",
        ["symbol", "timeframe", "created_at"],
    )
    op.create_index("ix_data_quality_events_symbol", "data_quality_events", ["symbol"])
    op.create_index(
        "ix_data_quality_events_timeframe",
        "data_quality_events",
        ["timeframe"],
    )
    op.create_index("ix_data_quality_events_source", "data_quality_events", ["source"])
    op.create_index(
        "ix_data_quality_events_category",
        "data_quality_events",
        ["category"],
    )
    op.create_index(
        "ix_data_quality_events_observed_at",
        "data_quality_events",
        ["observed_at"],
    )
    op.create_index(
        "ix_data_quality_events_effective_at",
        "data_quality_events",
        ["effective_at"],
    )
    op.create_index(
        "ix_data_quality_events_created_at",
        "data_quality_events",
        ["created_at"],
    )


def downgrade() -> None:
    for index_name in (
        "ix_data_quality_events_created_at",
        "ix_data_quality_events_effective_at",
        "ix_data_quality_events_observed_at",
        "ix_data_quality_events_category",
        "ix_data_quality_events_source",
        "ix_data_quality_events_timeframe",
        "ix_data_quality_events_symbol",
        "ix_data_quality_events_symbol_timeframe_created_at",
    ):
        op.drop_index(index_name, table_name="data_quality_events")
    op.drop_table("data_quality_events")
