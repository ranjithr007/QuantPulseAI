from datetime import datetime

from sqlalchemy import create_engine, inspect, text

from app.database.bootstrap import ensure_sqlite_market_candle_schema


def test_legacy_sqlite_candle_table_is_upgraded_and_backfilled():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE market_candles (
                    id INTEGER PRIMARY KEY,
                    symbol VARCHAR(20) NOT NULL,
                    timeframe VARCHAR(10),
                    open_price FLOAT,
                    high_price FLOAT,
                    low_price FLOAT,
                    close_price FLOAT,
                    volume FLOAT,
                    candle_time DATETIME
                )
                """
            )
        )
        connection.execute(
            text(
                """INSERT INTO market_candles
                 (symbol, timeframe, candle_time, close_price)
                 VALUES ('DOGEUSDT', '1h', :candle_time, 0.12)
                """
            ),
            {"candle_time": datetime(2026, 7, 27, 12)},
        )

    ensure_sqlite_market_candle_schema(engine)

    columns = {column["name"] for column in inspect(engine).get_columns("market_candles")}
    assert {"venue", "market_type", "open_time", "close_time", "is_final"}.issubset(columns)
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """SELECT venue, market_type, open_time, close_time, is_final, quality_state
                 FROM market_candles
                """
            )
        ).mappings().one()

    assert row["venue"] == "UNKNOWN"
    assert row["market_type"] == "FUTURES"
    assert row["open_time"] == row["close_time"]
    assert row["is_final"] == 1
    assert row["quality_state"] == "LEGACY_UNVERIFIED"
