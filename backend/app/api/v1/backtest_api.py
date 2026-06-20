from fastapi import APIRouter, Query

from app.backtesting.trade_simulator import execute_backtest


router = APIRouter(prefix="/backtest", tags=["Backtesting"])


@router.post("/{symbol}")
def backtest(symbol: str, signal: str):

    return execute_backtest(symbol, "15m", None, signal)


@router.get("/summary")
def backtest_summary(
    symbol: str,
    signal: str = Query(default="LONG", pattern="^(LONG|SHORT)$"),
    timeframe: str = Query(default="15m", pattern="^(1m|5m|15m|1h|4h|1d)$"),
):
    result = execute_backtest(symbol, timeframe, None, signal)

    return {
        "source": "backtest_summary",
        "symbol": symbol,
        "signal": signal,
        "timeframe": timeframe,
        "result": result,
    }
