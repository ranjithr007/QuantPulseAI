from app.database.sqlserver import SessionLocal

from app.repositories.candle_repository import get_latest_candles

from app.backtesting.backtest_engine import run_backtest

from app.backtesting.performance_engine import calculate_performance


def execute_backtest(symbol, timeframe, trade_plan, signal):

    db = SessionLocal()

    try:

        candles = get_latest_candles(db, symbol, timeframe, 500)

        if not candles:

            return {"message": "No candle data found", "symbol": symbol}

        result = run_backtest(candles, signal.upper())

        performance = calculate_performance(result["trades"])

        result.update(performance)

        return result

    finally:

        db.close()