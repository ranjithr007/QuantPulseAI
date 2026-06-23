from fastapi import APIRouter, Query

from app.database.models.market_candles import MarketCandle
from app.database.sqlserver import SessionLocal
from app.repositories.candle_repository import get_latest_candles
from app.utils.freshness import stale_after_seconds_for_timeframe
from app.utils.freshness import with_freshness


router = APIRouter(prefix="/market", tags=["Market"])


@router.get("/{symbol}/candles")
def get_market_candles(
    symbol: str,
    timeframe: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    stale_after_seconds: int | None = Query(default=None, ge=1),
):
    db = SessionLocal()

    try:
        return build_market_candles_payload(
            db,
            symbol,
            timeframe,
            limit,
            stale_after_seconds,
        )

    finally:
        db.close()


def build_market_candles_payload(db, symbol, timeframe=None, limit=100, stale_after_seconds=None):
    effective_stale_after_seconds = (
        stale_after_seconds
        if stale_after_seconds is not None
        else stale_after_seconds_for_timeframe(timeframe)
    )

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
        with_freshness(record, "candle_time", effective_stale_after_seconds)
        for record in records
    ]

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "count": len(items),
        "latest": items[0] if items else None,
        "records": items,
    }
