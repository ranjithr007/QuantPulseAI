"""enforce canonical candle contract

Revision ID: e7b3a914c2d6
Revises: d4f8a21c9b73
Create Date: 2026-07-27 09:30:00

"""

from typing import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "e7b3a914c2d6"
down_revision: Union[str, Sequence[str], None] = "d4f8a21c9b73"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()

    if connection.dialect.name == "mssql":
        op.execute(
            sa.text(
                """
                UPDATE market_candles
                SET
                    open_time = COALESCE(open_time, candle_time),
                    close_time = COALESCE(
                        close_time,
                        CASE timeframe
                            WHEN '1m' THEN DATEADD(minute, 1, candle_time)
                            WHEN '5m' THEN DATEADD(minute, 5, candle_time)
                            WHEN '15m' THEN DATEADD(minute, 15, candle_time)
                            WHEN '1h' THEN DATEADD(hour, 1, candle_time)
                            WHEN '4h' THEN DATEADD(hour, 4, candle_time)
                            WHEN '1d' THEN DATEADD(day, 1, candle_time)
                            ELSE DATEADD(minute, 1, candle_time)
                        END
                    ),
                    is_final = CASE
                        WHEN COALESCE(
                            close_time,
                            CASE timeframe
                                WHEN '1m' THEN DATEADD(minute, 1, candle_time)
                                WHEN '5m' THEN DATEADD(minute, 5, candle_time)
                                WHEN '15m' THEN DATEADD(minute, 15, candle_time)
                                WHEN '1h' THEN DATEADD(hour, 1, candle_time)
                                WHEN '4h' THEN DATEADD(hour, 4, candle_time)
                                WHEN '1d' THEN DATEADD(day, 1, candle_time)
                                ELSE DATEADD(minute, 1, candle_time)
                            END
                        ) <= SYSUTCDATETIME()
                        THEN 1
                        ELSE 0
                    END,
                    updated_at = SYSUTCDATETIME()
                WHERE open_time IS NULL OR close_time IS NULL
                """
            )
        )
    else:
        op.execute(
            sa.text(
                """
                UPDATE market_candles
                SET
                    open_time = COALESCE(open_time, candle_time),
                    close_time = COALESCE(
                        close_time,
                        CASE timeframe
                            WHEN '1m' THEN datetime(candle_time, '+1 minute')
                            WHEN '5m' THEN datetime(candle_time, '+5 minutes')
                            WHEN '15m' THEN datetime(candle_time, '+15 minutes')
                            WHEN '1h' THEN datetime(candle_time, '+1 hour')
                            WHEN '4h' THEN datetime(candle_time, '+4 hours')
                            WHEN '1d' THEN datetime(candle_time, '+1 day')
                            ELSE datetime(candle_time, '+1 minute')
                        END
                    ),
                    is_final = CASE
                        WHEN COALESCE(
                            close_time,
                            CASE timeframe
                                WHEN '1m' THEN datetime(candle_time, '+1 minute')
                                WHEN '5m' THEN datetime(candle_time, '+5 minutes')
                                WHEN '15m' THEN datetime(candle_time, '+15 minutes')
                                WHEN '1h' THEN datetime(candle_time, '+1 hour')
                                WHEN '4h' THEN datetime(candle_time, '+4 hours')
                                WHEN '1d' THEN datetime(candle_time, '+1 day')
                                ELSE datetime(candle_time, '+1 minute')
                            END
                        ) <= CURRENT_TIMESTAMP
                        THEN 1
                        ELSE 0
                    END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE open_time IS NULL OR close_time IS NULL
                """
            )
        )

    null_count = connection.execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM market_candles
            WHERE open_time IS NULL OR close_time IS NULL
            """
        )
    ).scalar()
    if int(null_count or 0) > 0:
        raise RuntimeError(
            "Canonical candle contract cannot be enforced while null "
            "open_time or close_time values remain."
        )

    duplicate_count = connection.execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM (
                SELECT
                    venue,
                    market_type,
                    symbol,
                    timeframe,
                    open_time
                FROM market_candles
                GROUP BY
                    venue,
                    market_type,
                    symbol,
                    timeframe,
                    open_time
                HAVING COUNT(*) > 1
            ) duplicate_identities
            """
        )
    ).scalar()
    if int(duplicate_count or 0) > 0:
        raise RuntimeError(
            "Canonical candle contract cannot be enforced while duplicate "
            "venue/market/symbol/timeframe/open_time rows remain."
        )

    op.drop_index(
        "uq_market_candles_canonical_identity",
        table_name="market_candles",
    )
    op.drop_index(
        "idx_market_candles_symbol_timeframe_open",
        table_name="market_candles",
    )
    if connection.dialect.name == "sqlite":
        with op.batch_alter_table("market_candles") as batch_op:
            batch_op.alter_column(
                "open_time",
                existing_type=sa.DateTime(),
                nullable=False,
            )
            batch_op.alter_column(
                "close_time",
                existing_type=sa.DateTime(),
                nullable=False,
            )
    else:
        op.alter_column(
            "market_candles",
            "open_time",
            existing_type=sa.DateTime(),
            nullable=False,
        )
        op.alter_column(
            "market_candles",
            "close_time",
            existing_type=sa.DateTime(),
            nullable=False,
        )
    op.create_index(
        "uq_market_candles_canonical_identity",
        "market_candles",
        ["venue", "market_type", "symbol", "timeframe", "open_time"],
        unique=True,
    )
    op.create_index(
        "idx_market_candles_symbol_timeframe_open",
        "market_candles",
        ["symbol", "timeframe", "open_time"],
        unique=False,
    )


def downgrade() -> None:
    connection = op.get_bind()
    op.drop_index(
        "uq_market_candles_canonical_identity",
        table_name="market_candles",
    )
    op.drop_index(
        "idx_market_candles_symbol_timeframe_open",
        table_name="market_candles",
    )
    if connection.dialect.name == "sqlite":
        with op.batch_alter_table("market_candles") as batch_op:
            batch_op.alter_column(
                "close_time",
                existing_type=sa.DateTime(),
                nullable=True,
            )
            batch_op.alter_column(
                "open_time",
                existing_type=sa.DateTime(),
                nullable=True,
            )
    else:
        op.alter_column(
            "market_candles",
            "close_time",
            existing_type=sa.DateTime(),
            nullable=True,
        )
        op.alter_column(
            "market_candles",
            "open_time",
            existing_type=sa.DateTime(),
            nullable=True,
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
