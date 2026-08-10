import importlib
import importlib.util
from datetime import datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.exc import IntegrityError


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "d4f8a21c9b73_add_canonical_candle_metadata.py"
)


def test_canonical_candle_migration_backfills_and_enforces_identity():
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    table = _legacy_market_candles(metadata)
    metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(
            table.insert(),
            [
                _legacy_row(1, "2026-07-26 10:00:00"),
                _legacy_row(2, "2026-07-26 11:00:00"),
            ],
        )
        _run_upgrade(connection)

        columns = {
            column["name"]
            for column in sa.inspect(connection).get_columns("market_candles")
        }
        assert {
            "venue",
            "market_type",
            "open_time",
            "close_time",
            "is_final",
            "source",
            "ingested_at",
            "updated_at",
            "revision",
            "quality_state",
        }.issubset(columns)

        migrated = connection.execute(
            sa.text(
                """
                SELECT venue, market_type, open_time, close_time, is_final,
                       source, revision, quality_state
                FROM market_candles
                WHERE id = 1
                """
            )
        ).mappings().one()
        assert migrated["venue"] == "UNKNOWN"
        assert migrated["market_type"] == "FUTURES"
        assert str(migrated["open_time"]).startswith("2026-07-26 10:00:00")
        assert str(migrated["close_time"]).startswith("2026-07-26 11:00:00")
        assert bool(migrated["is_final"]) is True
        assert migrated["source"] == "LEGACY_UNKNOWN"
        assert migrated["revision"] == 0
        assert migrated["quality_state"] == "LEGACY_UNVERIFIED"

        with pytest.raises(IntegrityError):
            connection.execute(
                sa.text(
                    """
                    INSERT INTO market_candles (
                        id, symbol, timeframe, candle_time, venue, market_type,
                        open_time
                    )
                    VALUES (
                        3, 'DOGEUSDT', '1h', '2026-07-26 10:00:00.000000',
                        'UNKNOWN', 'FUTURES', '2026-07-26 10:00:00.000000'
                    )
                    """
                )
            )


def test_canonical_candle_migration_refuses_legacy_duplicates():
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    table = _legacy_market_candles(metadata)
    metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(
            table.insert(),
            [
                _legacy_row(1, "2026-07-26 10:00:00"),
                _legacy_row(2, "2026-07-26 10:00:00"),
            ],
        )
        with pytest.raises(RuntimeError, match="duplicate legacy"):
            _run_upgrade(connection)


def _run_upgrade(connection):
    spec = importlib.util.spec_from_file_location(
        "r1_canonical_candle_migration",
        MIGRATION_PATH,
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    context = MigrationContext.configure(connection)
    migration.op = Operations(context)
    migration.upgrade()


def _legacy_market_candles(metadata):
    return sa.Table(
        "market_candles",
        metadata,
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("timeframe", sa.String(10)),
        sa.Column("open_price", sa.Float()),
        sa.Column("high_price", sa.Float()),
        sa.Column("low_price", sa.Float()),
        sa.Column("close_price", sa.Float()),
        sa.Column("volume", sa.Float()),
        sa.Column("candle_time", sa.DateTime()),
    )


def _legacy_row(identifier, candle_time):
    return {
        "id": identifier,
        "symbol": "DOGEUSDT",
        "timeframe": "1h",
        "open_price": 0.07,
        "high_price": 0.08,
        "low_price": 0.06,
        "close_price": 0.075,
        "volume": 1000,
        "candle_time": datetime.fromisoformat(candle_time),
    }
