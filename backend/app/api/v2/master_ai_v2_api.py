from fastapi import APIRouter, Query

from app.database.sqlserver import SessionLocal

from app.intelligence.contradiction_engine import build_contradiction_report
from app.intelligence.probability_engine import build_probability_profile
from app.repositories.intelligence_repository import get_ai_inputs

from app.intelligence.master_ai_engine import generate_master_signal
from app.trading.trade_plan_engine import build_trade_plan

from app.database.models.market_candles import MarketCandle
from app.repositories.candle_repository import get_latest_candle
from app.trading.trade_plan_engine import risk_level
from app.intelligence.signal_quality_engine import validate_signal
from app.risk.risk_engine import RiskEngine
from app.utils.freshness import freshness_status
from app.utils.signal_validation import validate_trade_plan_direction

router = APIRouter(prefix="/master-ai-v2", tags=["Master AI V2"])


@router.get("/{symbol}")
def master_ai(
    symbol: str,
    timeframe: str = Query(default="5m", enum=["1m", "5m", "15m", "1h", "4h", "1d"]),
    stale_after_seconds: int = Query(default=900, ge=1),
):
    return build_master_ai_response(symbol, timeframe, stale_after_seconds)


def build_master_ai_response(symbol: str, timeframe: str, stale_after_seconds: int = 900):

    db = SessionLocal()

    try:

        data = get_ai_inputs(db, symbol, timeframe)
        candle = get_latest_candle(db, symbol, timeframe)

        if not candle:

            return {
                "symbol": symbol,
                "timeframe": timeframe,
                "signal": "NO_DATA",
                "confidence": 0,
                "freshness": freshness_status(None, stale_after_seconds),
                "message": "No latest candle found for symbol/timeframe",
                "contradiction": build_contradiction_report(
                    db,
                    symbol,
                    timeframe,
                    stale_after_seconds,
                ),
                "probability": build_probability_profile(
                    db,
                    symbol,
                    timeframe,
                    stale_after_seconds,
                ),
            }

        result = generate_master_signal(
            data["feature"], data["regime"], data["orderflow"], data["smc"]
        )
        result["symbol"] = symbol
        result["timeframe"] = timeframe

        current_price = float(candle.close_price)
        atr = _latest_atr(data["feature"], current_price)
        trade = build_trade_plan(result["signal"], current_price, atr)
        validation = validate_trade_plan_direction(
            result["signal"], trade["entry"], trade["target1"]
        )

        result["trade_plan"] = trade
        result["trade_plan_validation"] = validation
        result["current_price"] = current_price
        result["candle_time"] = candle.candle_time
        result["freshness"] = freshness_status(candle.candle_time, stale_after_seconds)
        result["inputs"] = {
            "feature": freshness_status(
                getattr(data["feature"], "CreatedAt", None),
                stale_after_seconds,
            ),
            "regime": freshness_status(
                getattr(data["regime"], "CreatedAt", None),
                stale_after_seconds,
            ),
            "orderflow": freshness_status(
                getattr(data["orderflow"], "CreatedAt", None),
                stale_after_seconds,
            ),
            "smc": freshness_status(
                getattr(data["smc"], "created_at", None),
                stale_after_seconds,
            ),
        }

        quality = validate_signal(
            result["signal"],
            result["confidence"],
            trade,
            data["regime"],
            data["orderflow"],
            data["smc"],
        )

        result["quality"] = quality
        result["contradiction"] = build_contradiction_report(
            db,
            symbol,
            timeframe,
            stale_after_seconds,
        )
        result["probability"] = build_probability_profile(
            db,
            symbol,
            timeframe,
            stale_after_seconds,
        )
        risk_engine = RiskEngine()
        risk = risk_engine.analyze(
            symbol,
            result["signal"],
            current_price,
            trade["atr"],
            result["confidence"],
        )

        result["risk_management"] = risk
        result["risk"] = risk_level(result["confidence"])

        return result

    finally:

        db.close()


def _latest_atr(feature, current_price):
    atr = getattr(feature, "ATR", None) if feature else None

    if atr and atr > 0:
        return float(atr)

    return current_price * 0.01
