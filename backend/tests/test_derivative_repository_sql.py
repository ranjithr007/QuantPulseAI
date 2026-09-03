from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy import true
from sqlalchemy.dialects import mssql
from sqlalchemy.orm import Query
from sqlalchemy.orm import sessionmaker

from app.database.models.futures_mark_prices import FuturesMarkPrice
from app.repositories.derivative_repository import DerivativeRepository


def test_final_mark_price_predicate_compiles_for_sql_server():
    statement = Query(FuturesMarkPrice).filter(
        FuturesMarkPrice.is_final == true()
    ).statement
    sql = str(
        statement.compile(
            dialect=mssql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "is_final = 1" in sql
    assert "is_final IS 1" not in sql


def test_latest_mark_prices_returns_one_latest_final_row_per_symbol():
    engine = create_engine("sqlite://")
    FuturesMarkPrice.__table__.create(bind=engine)
    session_factory = sessionmaker(bind=engine)
    now = datetime(2026, 9, 3, 8, 0)

    with session_factory() as db:
        db.add_all(
            [
                _mark(1, "BTCUSDT", now, 100.0),
                _mark(2, "BTCUSDT", now + timedelta(minutes=5), 101.0),
                _mark(3, "ETHUSDT", now + timedelta(minutes=5), 201.0),
                _mark(4, "ETHUSDT", now + timedelta(minutes=10), 202.0, final=False),
                _mark(5, "SOLUSDT", now + timedelta(hours=1), 50.0, timeframe="1h"),
            ]
        )
        db.commit()

        result = DerivativeRepository().latest_mark_prices(
            db,
            ["btcusdt", "ETHUSDT", "MISSINGUSDT"],
            timeframe="5m",
        )

        assert set(result) == {"BTCUSDT", "ETHUSDT"}
        assert result["BTCUSDT"].close_price == 101.0
        assert result["ETHUSDT"].close_price == 201.0

    engine.dispose()


def _mark(identifier, symbol, close_time, close_price, *, final=True, timeframe="5m"):
    return FuturesMarkPrice(
        id=identifier,
        venue="BINANCE",
        market_type="USDT_FUTURES",
        symbol=symbol,
        timeframe=timeframe,
        open_time=close_time - timedelta(minutes=5),
        close_time=close_time,
        open_price=close_price,
        high_price=close_price,
        low_price=close_price,
        close_price=close_price,
        is_final=final,
        source="TEST",
    )
