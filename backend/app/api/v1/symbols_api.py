from fastapi import APIRouter, Query

from app.database.models.market_candles import MarketCandle
from app.database.models.symbols import Symbol
from app.database.sqlserver import SessionLocal
from app.repositories.candle_repository import get_latest_candle
from app.repositories.symbol_repository import SymbolRepository
from app.utils.freshness import freshness_status


DEFAULT_SYMBOLS = [
    ("BTCUSDT", "BTC", "USDT"),
    ("ETHUSDT", "ETH", "USDT"),
    ("XRPUSDT", "XRP", "USDT"),
    ("DOGEUSDT", "DOGE", "USDT"),
    ("SOLUSDT", "SOL", "USDT"),
    ("BNBUSDT", "BNB", "USDT"),
]


router = APIRouter(prefix="/symbols", tags=["Symbols"])


@router.get("")
def list_symbols(
    timeframe: str = Query(default="5m"),
    stale_after_seconds: int = Query(default=900, ge=1),
):
    db = SessionLocal()

    try:
        symbols = SymbolRepository().get_active_symbols(db)
        records = [
            _symbol_coverage(db, item, timeframe, stale_after_seconds)
            for item in symbols
        ]

        return {
            "timeframe": timeframe,
            "count": len(records),
            "active_count": len([item for item in records if item["is_active"]]),
            "records": records,
        }

    finally:
        db.close()


@router.post("/seed")
def seed_default_symbols():
    db = SessionLocal()
    created = []
    activated = []

    try:
        for symbol, base_asset, quote_asset in DEFAULT_SYMBOLS:
            record = db.query(Symbol).filter(Symbol.symbol == symbol).first()

            if record is None:
                record = Symbol(
                    symbol=symbol,
                    base_asset=base_asset,
                    quote_asset=quote_asset,
                    is_active=True,
                )
                db.add(record)
                created.append(symbol)
                continue

            if not record.is_active:
                record.is_active = True
                activated.append(symbol)

        db.commit()

        return {
            "created": created,
            "activated": activated,
            "default_symbols": [symbol for symbol, _base, _quote in DEFAULT_SYMBOLS],
        }

    finally:
        db.close()


def _symbol_coverage(db, symbol, timeframe, stale_after_seconds):
    latest = get_latest_candle(db, symbol.symbol, timeframe)
    count = (
        db.query(MarketCandle)
        .filter(MarketCandle.symbol == symbol.symbol)
        .filter(MarketCandle.timeframe == timeframe)
        .count()
    )

    return {
        "symbol": symbol.symbol,
        "base_asset": symbol.base_asset,
        "quote_asset": symbol.quote_asset,
        "is_active": symbol.is_active,
        "timeframe": timeframe,
        "candle_count": count,
        "latest_candle_time": latest.candle_time if latest else None,
        "latest_close": latest.close_price if latest else None,
        "freshness": freshness_status(
            latest.candle_time if latest else None,
            stale_after_seconds,
        ),
    }
