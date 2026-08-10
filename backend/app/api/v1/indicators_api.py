from fastapi import APIRouter, Query

from app.database.models.market_candles import MarketCandle
from app.database.sqlserver import SessionLocal
from app.engines.technical_engine import TechnicalEngine
from app.engines.volatility_engine import VolatilityEngine
from app.repositories.candle_repository import get_latest_candles
from app.utils.freshness import candle_freshness_timestamp, freshness_status


router = APIRouter(prefix="/indicators", tags=["Indicators"])


@router.get("/{symbol}")
def get_indicators(
    symbol: str,
    timeframe: str = Query(default="5m"),
    limit: int = Query(default=100, ge=20, le=500),
    stale_after_seconds: int = Query(default=900, ge=1),
):
    db = SessionLocal()

    try:
        candles = get_latest_candles(db, symbol, timeframe, limit)

        if not candles:
            return {
                "symbol": symbol,
                "timeframe": timeframe,
                "signal": "NO_DATA",
                "freshness": freshness_status(None, stale_after_seconds),
            }

        latest = candles[-1]

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "count": len(candles),
            "latest_close": latest.close_price,
            "latest_candle_time": latest.candle_time,
            "freshness": freshness_status(
                candle_freshness_timestamp(latest),
                stale_after_seconds,
            ),
            "technical": TechnicalEngine().analyze(candles),
            "volatility": VolatilityEngine().analyze(candles),
        }

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()
