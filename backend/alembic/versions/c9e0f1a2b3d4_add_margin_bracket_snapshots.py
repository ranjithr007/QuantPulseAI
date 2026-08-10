"""add versioned futures margin bracket snapshots

Revision ID: c9e0f1a2b3d4
Revises: b8d9e0f1a2c3
Create Date: 2026-07-27 21:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c9e0f1a2b3d4"
down_revision: Union[str, Sequence[str], None] = "b8d9e0f1a2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "futures_margin_brackets",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("venue", sa.String(length=20), nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("snapshot_version", sa.String(length=64), nullable=False),
        sa.Column("effective_at", sa.DateTime(), nullable=False),
        sa.Column("bracket_number", sa.Integer(), nullable=False),
        sa.Column("notional_floor", sa.Float(), nullable=False),
        sa.Column("notional_cap", sa.Float(), nullable=False),
        sa.Column("initial_leverage", sa.Float(), nullable=True),
        sa.Column("maintenance_margin_rate", sa.Float(), nullable=False),
        sa.Column("maintenance_amount", sa.Float(), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "venue",
            "symbol",
            "snapshot_version",
            "bracket_number",
            name="uq_futures_margin_bracket_snapshot",
        ),
    )
    op.create_index(
        "ix_futures_margin_brackets_symbol",
        "futures_margin_brackets",
        ["symbol"],
        unique=False,
    )
    op.create_index(
        "ix_futures_margin_brackets_as_of",
        "futures_margin_brackets",
        ["symbol", "effective_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_futures_margin_brackets_as_of",
        table_name="futures_margin_brackets",
    )
    op.drop_index(
        "ix_futures_margin_brackets_symbol",
        table_name="futures_margin_brackets",
    )
    op.drop_table("futures_margin_brackets")
