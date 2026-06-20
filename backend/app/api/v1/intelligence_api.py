from fastapi import APIRouter, Query

from app.api.v1.ai_scores_api import get_ai_scores
from app.api.v1.market_api import get_market_candles
from app.api.v1.orderflow_api import get_orderflow
from app.api.v1.risk_api import get_risk
from app.api.v1.signals_api import build_entry_trigger_payload
from app.api.v1.signals_api import build_multi_timeframe_signal_payload
from app.api.v1.signals_api import build_signal_payload
from app.api.v1.signals_api import build_trade_setup_payload
from app.api.v1.signals_api import get_signal_diagnostics
from app.api.v1.smc_api import get_smc
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


@router.get("/{symbol}/bundle")
def get_intelligence_bundle(
    symbol: str,
    timeframe: str = Query(default="1h"),
    mode: str | None = Query(default=None),
    stale_after_seconds: int = Query(default=900, ge=1),
):
    db = SessionLocal()

    try:
        signal = build_signal_payload(db, symbol, timeframe=timeframe, stale_after_seconds=stale_after_seconds)
        diagnostics = get_signal_diagnostics(symbol, timeframe=timeframe, stale_after_seconds=stale_after_seconds)
        candles = get_market_candles(symbol, timeframe=timeframe, limit=80, stale_after_seconds=stale_after_seconds)
        orderflow = get_orderflow(symbol, timeframe=timeframe, limit=20, stale_after_seconds=stale_after_seconds)
        smc = get_smc(symbol, timeframe=timeframe, limit=20, stale_after_seconds=stale_after_seconds)
        risk = get_risk(symbol, stale_after_seconds=stale_after_seconds)
        ai_scores = get_ai_scores(symbol, timeframe=timeframe, limit=20, stale_after_seconds=stale_after_seconds)
        multi_timeframe = build_multi_timeframe_signal_payload(
            db=db,
            symbol=symbol,
            mode=mode,
            lower=None,
            middle=None,
            higher=None,
            stale_after_seconds=stale_after_seconds,
        )
        trade_setup = build_trade_setup_payload(
            db=db,
            symbol=symbol,
            mode=mode,
            lower=None,
            middle=None,
            higher=None,
            stale_after_seconds=stale_after_seconds,
        )
        entry_trigger = build_entry_trigger_payload(
            db=db,
            symbol=symbol,
            mode=mode,
            lower=None,
            middle=None,
            higher=None,
            stale_after_seconds=stale_after_seconds,
        )

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "mode": mode,
            "stale_after_seconds": stale_after_seconds,
            "source": "intelligence_bundle",
            "signal": signal,
            "diagnostics": diagnostics,
            "candles": candles,
            "orderflow": orderflow,
            "smc": smc,
            "risk": risk,
            "aiScores": ai_scores,
            "multiTimeframe": multi_timeframe,
            "tradeSetup": trade_setup,
            "entryTrigger": entry_trigger,
        }
    finally:
        db.close()
