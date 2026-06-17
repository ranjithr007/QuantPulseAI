from fastapi import APIRouter, Query

from app.database.models.market_candles import MarketCandle
from app.database.sqlserver import SessionLocal
from app.intelligence.master_ai_engine import generate_master_signal
from app.repositories.candle_repository import get_latest_candle
from app.repositories.intelligence_repository import get_ai_inputs
from app.trading.trade_plan_engine import build_trade_plan
from app.utils.freshness import freshness_status


router = APIRouter(prefix="/intelligence", tags=["Intelligence"])


@router.get("/{symbol}/snapshot")
def get_intelligence_snapshot(
    symbol: str,
    timeframe: str = Query(default="5m"),
    stale_after_seconds: int = Query(default=900, ge=1),
):
    db = SessionLocal()

    try:
        candle = get_latest_candle(db, symbol, timeframe)

        if not candle:
            return {
                "symbol": symbol,
                "timeframe": timeframe,
                "signal": "NO_DATA",
                "freshness": freshness_status(None, stale_after_seconds),
            }

        inputs = get_ai_inputs(db, symbol, timeframe)
        signal = generate_master_signal(
            inputs["feature"], inputs["regime"], inputs["orderflow"], inputs["smc"]
        )
        current_price = float(candle.close_price)
        atr = getattr(inputs["feature"], "ATR", None) or current_price * 0.01

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "current_price": current_price,
            "candle_time": candle.candle_time,
            "freshness": freshness_status(candle.candle_time, stale_after_seconds),
            "signal": signal,
            "trade_plan": build_trade_plan(signal["signal"], current_price, atr),
            "inputs": {
                "feature": freshness_status(
                    getattr(inputs["feature"], "CreatedAt", None),
                    stale_after_seconds,
                ),
                "regime": freshness_status(
                    getattr(inputs["regime"], "CreatedAt", None),
                    stale_after_seconds,
                ),
                "orderflow": freshness_status(
                    getattr(inputs["orderflow"], "CreatedAt", None),
                    stale_after_seconds,
                ),
                "smc": freshness_status(
                    getattr(inputs["smc"], "created_at", None),
                    stale_after_seconds,
                ),
            },
        }

    finally:
        db.close()
