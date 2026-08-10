from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.database.models.market_candles import MarketCandle
from app.database.models.symbols import Symbol
from app.database.sqlserver import Base


DEFAULT_FUTURES_SYMBOLS = (
    ("BTCUSDT", "BTC", "USDT"),
    ("ETHUSDT", "ETH", "USDT"),
    ("XRPUSDT", "XRP", "USDT"),
    ("DOGEUSDT", "DOGE", "USDT"),
    ("SOLUSDT", "SOL", "USDT"),
    ("BNBUSDT", "BNB", "USDT"),
)


def bootstrap_sqlite_demo_data(engine):
    """Create the SQLite fallback schema and seed the futures watchlist."""

    Base.metadata.create_all(bind=engine)
    ensure_sqlite_market_candle_schema(engine)

    with Session(engine) as db:
        existing = {
            record.symbol: record
            for record in db.query(Symbol)
            .filter(Symbol.symbol.in_([item[0] for item in DEFAULT_FUTURES_SYMBOLS]))
            .all()
        }

        for symbol, base_asset, quote_asset in DEFAULT_FUTURES_SYMBOLS:
            record = existing.get(symbol)
            if record is None:
                db.add(
                    Symbol(
                        symbol=symbol,
                        base_asset=base_asset,
                        quote_asset=quote_asset,
                        is_active=True,
                    )
                )
                continue

            record.base_asset = base_asset
            record.quote_asset = quote_asset
            record.is_active = True

        db.commit()


def ensure_sqlite_market_candle_schema(engine):
    """Bring an older SQLite fallback candle table up to the current model shape.

    The development fallback database predates the canonical futures candle
    columns. ``create_all`` does not alter an existing table, so add only the
    missing nullable/defaulted columns and backfill legacy rows from
    ``candle_time``. SQL Server remains migration-managed and is untouched.
    """

    if getattr(engine.dialect, "name", "") != "sqlite":
        return

    MarketCandle.__table__.create(bind=engine, checkfirst=True)
    inspector = inspect(engine)
    existing = {column["name"] for column in inspector.get_columns("market_candles")}
    additions = {
        "venue": "VARCHAR(20) DEFAULT 'UNKNOWN'",
        "market_type": "VARCHAR(20) DEFAULT 'FUTURES'",
        "open_time": "DATETIME",
        "close_time": "DATETIME",
        "is_final": "BOOLEAN DEFAULT 1",
        "source": "VARCHAR(40) DEFAULT 'LEGACY_UNKNOWN'",
        "ingested_at": "DATETIME",
        "updated_at": "DATETIME",
        "revision": "INTEGER DEFAULT 0",
        "quality_state": "VARCHAR(30) DEFAULT 'LEGACY_UNVERIFIED'",
    }

    with engine.begin() as connection:
        for column, definition in additions.items():
            if column not in existing:
                connection.execute(
                    text(f"ALTER TABLE market_candles ADD COLUMN {column} {definition}")
                )

        connection.execute(
            text(
                """
                UPDATE market_candles
                SET open_time = COALESCE(open_time, candle_time),
                    close_time = COALESCE(close_time, candle_time),
                    is_final = COALESCE(is_final, 1),
                    venue = COALESCE(venue, 'UNKNOWN'),
                    market_type = COALESCE(market_type, 'FUTURES'),
                    source = COALESCE(source, 'LEGACY_UNKNOWN'),
                    revision = COALESCE(revision, 0),
                    quality_state = COALESCE(quality_state, 'LEGACY_UNVERIFIED'),
                    ingested_at = COALESCE(ingested_at, CURRENT_TIMESTAMP),
                    updated_at = COALESCE(updated_at, CURRENT_TIMESTAMP)
                """
            )
        )
