from fastapi import APIRouter, Query

from app.database.sqlserver import SessionLocal

from app.repositories.intelligence_repository import get_ai_inputs

from app.intelligence.master_ai_engine import generate_master_signal
from app.trading.trade_plan_engine import build_trade_plan

from app.database.models.market_candles import MarketCandle
from app.trading.trade_plan_engine import risk_level
from app.intelligence.signal_quality_engine import validate_signal
from app.risk.risk_engine import RiskEngine

router = APIRouter(prefix="/master-ai-v2", tags=["Master AI V2"])


@router.get("/{symbol}")
def master_ai(symbol: str, timeframe: str = Query(default="5m", enum=["1m", "5m", "15m", "1h", "4h", "1d"])):

    db = SessionLocal()

    try:

        data = get_ai_inputs(db, symbol, timeframe)
        price = (
            db.query(MarketCandle.close_price)
            .filter(MarketCandle.symbol == symbol)
            .order_by(MarketCandle.candle_time.desc())
            .first()
        )
        result = generate_master_signal(
            data["feature"], data["regime"], data["orderflow"], data["smc"]
        )
        result["symbol"] = symbol
        result["timeframe"] = timeframe
        trade = build_trade_plan(result["signal"], price[0])
        result["trade_plan"] = trade
        quality = validate_signal(
            result["signal"],
            result["confidence"],
            trade,
            data["regime"],
            data["orderflow"],
            data["smc"],
        )

        result["quality"] = quality
        risk = RiskEngine.analyze(symbol, result["signal"],price[0], trade["atr"], result["confidence"])

        result["risk_management"] = risk
        result["risk"] = risk_level(result["confidence"])

        return result

    finally:

        db.close()