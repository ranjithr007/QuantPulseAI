"""add futures mark price history

Revision ID: b8d9e0f1a2c3
Revises: a7c8d9e0f1b2
Create Date: 2026-07-27 20:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b8d9e0f1a2c3"
down_revision: Union[str, Sequence[str], None] = "a7c8d9e0f1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "futures_mark_prices",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("venue", sa.String(length=20), nullable=False),
        sa.Column("market_type", sa.String(length=20), nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("timeframe", sa.String(length=10), nullable=False),
        sa.Column("open_time", sa.DateTime(), nullable=False),
        sa.Column("close_time", sa.DateTime(), nullable=False),
        sa.Column("open_price", sa.Float(), nullable=False),
        sa.Column("high_price", sa.Float(), nullable=False),
        sa.Column("low_price", sa.Float(), nullable=False),
        sa.Column("close_price", sa.Float(), nullable=False),
        sa.Column("is_final", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "venue",
            "market_type",
            "symbol",
            "timeframe",
            "open_time",
            name="uq_futures_mark_price_identity",
        ),
    )
    op.create_index(
        "ix_futures_mark_prices_symbol",
        "futures_mark_prices",
        ["symbol"],
        unique=False,
    )
    op.create_index(
        "ix_futures_mark_prices_lookup",
        "futures_mark_prices",
        ["symbol", "timeframe", "close_time"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_futures_mark_prices_lookup", table_name="futures_mark_prices")
    op.drop_index("ix_futures_mark_prices_symbol", table_name="futures_mark_prices")
    op.drop_table("futures_mark_prices")
