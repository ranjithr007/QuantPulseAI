"""add canonical candle metadata

Revision ID: d4f8a21c9b73
Revises: cf39f6041cc2
Create Date: 2026-07-26 23:40:00

"""

from typing import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4f8a21c9b73"
down_revision: Union[str, Sequence[str], None] = "cf39f6041cc2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    sqlite = connection.dialect.name == "sqlite"
    duplicate_count = connection.execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM (
                SELECT symbol, timeframe, candle_time
                FROM market_candles
                GROUP BY symbol, timeframe, candle_time
                HAVING COUNT(*) > 1
            ) duplicate_identities
            """
        )
    ).scalar()
    if int(duplicate_count or 0) > 0:
        raise RuntimeError(
            "Cannot add canonical candle identity while duplicate legacy "
            "symbol/timeframe/candle_time rows exist."
        )

    op.add_column(
        "market_candles",
        sa.Column(
            "venue",
            sa.String(length=20),
            nullable=False,
            server_default="UNKNOWN",
        ),
    )
    op.add_column(
        "market_candles",
        sa.Column(
            "market_type",
            sa.String(length=20),
            nullable=False,
            server_default="FUTURES",
        ),
    )
    op.add_column(
        "market_candles",
        sa.Column("open_time", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "market_candles",
        sa.Column("close_time", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "market_candles",
        sa.Column(
            "is_final",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "market_candles",
        sa.Column(
            "source",
            sa.String(length=40),
            nullable=False,
            server_default="LEGACY_UNKNOWN",
        ),
    )
    op.add_column(
        "market_candles",
        sa.Column(
            "ingested_at",
            sa.DateTime(),
            nullable=sqlite,
            server_default=None if sqlite else sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.add_column(
        "market_candles",
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=sqlite,
            server_default=None if sqlite else sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.add_column(
        "market_candles",
        sa.Column(
            "revision",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "market_candles",
        sa.Column(
            "quality_state",
            sa.String(length=30),
            nullable=False,
            server_default="LEGACY_UNVERIFIED",
        ),
    )

    if connection.dialect.name == "mssql":
        op.execute(
            sa.text(
                """
                UPDATE market_candles
                SET
                    open_time = candle_time,
                    close_time = CASE timeframe
                        WHEN '1m' THEN DATEADD(minute, 1, candle_time)
                        WHEN '5m' THEN DATEADD(minute, 5, candle_time)
                        WHEN '15m' THEN DATEADD(minute, 15, candle_time)
                        WHEN '1h' THEN DATEADD(hour, 1, candle_time)
                        WHEN '4h' THEN DATEADD(hour, 4, candle_time)
                        WHEN '1d' THEN DATEADD(day, 1, candle_time)
                        ELSE DATEADD(minute, 1, candle_time)
                    END,
                    is_final = 1,
                    venue = 'UNKNOWN',
                    market_type = 'FUTURES',
                    source = 'LEGACY_UNKNOWN',
                    quality_state = 'LEGACY_UNVERIFIED',
                    revision = 0,
                    ingested_at = SYSUTCDATETIME(),
                    updated_at = SYSUTCDATETIME()
                """
            )
        )
    else:
        op.execute(
            sa.text(
                """
                UPDATE market_candles
                SET
                    open_time = candle_time,
                    close_time = CASE timeframe
                        WHEN '1m' THEN datetime(candle_time, '+1 minute')
                        WHEN '5m' THEN datetime(candle_time, '+5 minutes')
                        WHEN '15m' THEN datetime(candle_time, '+15 minutes')
                        WHEN '1h' THEN datetime(candle_time, '+1 hour')
                        WHEN '4h' THEN datetime(candle_time, '+4 hours')
                        WHEN '1d' THEN datetime(candle_time, '+1 day')
                        ELSE datetime(candle_time, '+1 minute')
                    END,
                    is_final = 1,
                    venue = 'UNKNOWN',
                    market_type = 'FUTURES',
                    source = 'LEGACY_UNKNOWN',
                    quality_state = 'LEGACY_UNVERIFIED',
                    revision = 0,
                    ingested_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                """
            )
        )

    op.create_index(
        "uq_market_candles_canonical_identity",
        "market_candles",
        ["venue", "market_type", "symbol", "timeframe", "open_time"],
        unique=True,
        mssql_where=sa.text("open_time IS NOT NULL"),
        sqlite_where=sa.text("open_time IS NOT NULL"),
    )
    op.create_index(
        "idx_market_candles_symbol_timeframe_open",
        "market_candles",
        ["symbol", "timeframe", "open_time"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "idx_market_candles_symbol_timeframe_open",
        table_name="market_candles",
    )
    op.drop_index(
        "uq_market_candles_canonical_identity",
        table_name="market_candles",
    )
    for column_name in (
        "quality_state",
        "revision",
        "updated_at",
        "ingested_at",
        "source",
        "is_final",
        "close_time",
        "open_time",
        "market_type",
        "venue",
    ):
        op.drop_column("market_candles", column_name)
