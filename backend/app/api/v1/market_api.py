from fastapi import APIRouter, Query

from app.database.models.market_candles import MarketCandle
from app.database.sqlserver import SessionLocal
from app.repositories.candle_repository import get_latest_candles
from app.utils.freshness import with_freshness


router = APIRouter(prefix="/market", tags=["Market"])


@router.get("/{symbol}/candles")
def get_market_candles(
    symbol: str,
    timeframe: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    stale_after_seconds: int = Query(default=900, ge=1),
):
    db = SessionLocal()

    try:
        if timeframe:
            records = get_latest_candles(db, symbol, timeframe, limit)
        else:
            records = (
                db.query(MarketCandle)
                .filter(MarketCandle.symbol == symbol)
                .order_by(MarketCandle.candle_time.desc())
                .limit(limit)
                .all()
            )

        items = [
            with_freshness(record, "candle_time", stale_after_seconds)
            for record in records
        ]

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "count": len(items),
            "latest": items[0] if items else None,
            "records": items,
        }

    finally:
        db.close()
