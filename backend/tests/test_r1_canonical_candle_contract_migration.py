import importlib.util
from datetime import datetime
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"
EXPAND_MIGRATION = (
    VERSIONS / "d4f8a21c9b73_add_canonical_candle_metadata.py"
)
CONTRACT_MIGRATION = (
    VERSIONS / "e7b3a914c2d6_enforce_canonical_candle_contract.py"
)


def test_contract_migration_repairs_compatibility_rows_and_closes_null_window():
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    table = _legacy_market_candles(metadata)
    metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(table.insert(), [_legacy_row(1)])
        _run_upgrade(connection, EXPAND_MIGRATION, "expand_candles")
        connection.execute(
            sa.text(
                """
                INSERT INTO market_candles (
                    id,
                    symbol,
                    timeframe,
                    open_price,
                    high_price,
                    low_price,
                    close_price,
                    volume,
                    candle_time
                )
                VALUES (
                    2,
                    'DOGEUSDT',
                    '1h',
                    0.07,
                    0.08,
                    0.06,
                    0.075,
                    1000,
                    '2026-07-26 11:00:00'
                )
                """
            )
        )

        _run_upgrade(connection, CONTRACT_MIGRATION, "contract_candles")

        repaired = connection.execute(
            sa.text(
                """
                SELECT open_time, close_time, is_final
                FROM market_candles
                WHERE id = 2
                """
            )
        ).mappings().one()
        assert str(repaired["open_time"]).startswith("2026-07-26 11:00:00")
        assert str(repaired["close_time"]).startswith("2026-07-26 12:00:00")
        assert bool(repaired["is_final"]) is True

        columns = {
            column["name"]: column
            for column in sa.inspect(connection).get_columns("market_candles")
        }
        assert columns["open_time"]["nullable"] is False
        assert columns["close_time"]["nullable"] is False


def _run_upgrade(connection, path, module_name):
    spec = importlib.util.spec_from_file_location(module_name, path)
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


def _legacy_row(identifier):
    return {
        "id": identifier,
        "symbol": "DOGEUSDT",
        "timeframe": "1h",
        "open_price": 0.07,
        "high_price": 0.08,
        "low_price": 0.06,
        "close_price": 0.075,
        "volume": 1000,
        "candle_time": datetime.fromisoformat("2026-07-26 10:00:00"),
    }
