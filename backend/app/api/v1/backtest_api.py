from fastapi import APIRouter

from app.backtesting.trade_simulator import execute_backtest


router = APIRouter(prefix="/backtest", tags=["Backtesting"])


@router.post("/{symbol}")
def backtest(symbol: str, signal: str):

    return execute_backtest(symbol, "15m", None, signal)