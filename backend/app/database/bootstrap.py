from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.database.models.market_candles import MarketCandle
from app.database.models.symbols import Symbol
from app.database.sqlserver import Base
from app.strategies.registry import LEGACY_UNATTRIBUTED_STRATEGY_ID
from app.strategies.registry import LEGACY_UNATTRIBUTED_STRATEGY_VERSION


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
    ensure_sqlite_strategy_attribution_schema(engine)

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


def ensure_sqlite_strategy_attribution_schema(engine):
    """Upgrade legacy development databases with durable strategy lineage.

    Production databases remain Alembic-managed.  The SQLite fallback is
    intentionally self-healing because ``metadata.create_all`` cannot alter an
    existing table and developers commonly keep the same local evidence file
    across releases.
    """

    if getattr(engine.dialect, "name", "") != "sqlite":
        return

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    additions = {
        "decision_snapshots": {
            "strategy_id": "VARCHAR(50)",
            "strategy_version": "VARCHAR(50)",
        },
        "trade_plans": {
            "strategy_id": "VARCHAR(50)",
            "strategy_version": "VARCHAR(50)",
            "strategy_decision_snapshot_id": "INTEGER",
        },
        "risk_decisions": {
            "trade_plan_id": "INTEGER",
            "strategy_id": "VARCHAR(50)",
            "strategy_version": "VARCHAR(50)",
            "strategy_decision_snapshot_id": "INTEGER",
        },
        "paper_trades": {
            "strategy_id": "VARCHAR(50)",
            "strategy_version": "VARCHAR(50)",
            "strategy_decision_snapshot_id": "INTEGER",
        },
    }

    with engine.begin() as connection:
        for table_name, columns in additions.items():
            if table_name not in tables:
                continue
            existing = {
                column["name"]
                for column in inspect(engine).get_columns(table_name)
            }
            for column_name, definition in columns.items():
                if column_name not in existing:
                    connection.execute(
                        text(
                            f"ALTER TABLE {table_name} ADD COLUMN "
                            f"{column_name} {definition}"
                        )
                    )

        params = {
            "strategy_id": LEGACY_UNATTRIBUTED_STRATEGY_ID,
            "strategy_version": LEGACY_UNATTRIBUTED_STRATEGY_VERSION,
        }
        for table_name in ("trade_plans", "risk_decisions", "paper_trades"):
            if table_name in tables:
                connection.execute(
                    text(
                        f"UPDATE {table_name} "
                        "SET strategy_id = COALESCE(strategy_id, :strategy_id), "
                        "strategy_version = COALESCE(strategy_version, :strategy_version)"
                    ),
                    params,
                )
        if "decision_snapshots" in tables:
            connection.execute(
                text(
                    "UPDATE decision_snapshots "
                    "SET strategy_id = COALESCE(strategy_id, :strategy_id), "
                    "strategy_version = COALESCE(strategy_version, :strategy_version) "
                    "WHERE strategy_id IS NULL OR strategy_version IS NULL"
                ),
                params,
            )

        for table_name, columns in additions.items():
            if table_name not in tables:
                continue
            for column_name in columns:
                index_name = f"ix_{table_name}_{column_name}"
                connection.execute(
                    text(
                        f"CREATE INDEX IF NOT EXISTS {index_name} "
                        f"ON {table_name} ({column_name})"
                    )
                )
