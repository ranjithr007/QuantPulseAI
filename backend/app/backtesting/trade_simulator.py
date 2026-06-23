from app.database.sqlserver import SessionLocal

from app.repositories.candle_repository import get_latest_candles

from app.backtesting.backtest_engine import run_backtest
from app.backtesting.walk_forward_validator import run_walk_forward

def execute_backtest(
    symbol,
    timeframe,
    trade_plan,
    signal,
    *,
    limit=500,
    initial_capital=10_000,
    position_size_percent=100,
    stop_percent=1,
    target_percent=2,
    fee_bps=4,
    slippage_bps=2,
):

    db = SessionLocal()

    try:

        candles = get_latest_candles(db, symbol, timeframe, limit)

        if not candles:

            return {
                "engine_version": "backtester_v2",
                "message": "No candle data found",
                "symbol": symbol,
                "timeframe": timeframe,
                "total_trades": 0,
                "trades": [],
            }

        result = run_backtest(
            candles,
            signal.upper(),
            stop_percent=stop_percent,
            target_percent=target_percent,
            initial_capital=initial_capital,
            position_size_percent=position_size_percent,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
        )
        result.update({"symbol": symbol, "timeframe": timeframe})

        return result

    finally:

        db.close()


def execute_walk_forward(
    symbol,
    timeframe,
    signal,
    *,
    limit=1000,
    stop_grid=(0.75, 1.0, 1.25, 1.5),
    target_grid=(1.5, 2.0, 2.5, 3.0),
    train_size=200,
    test_size=50,
    step_size=50,
    mode="EXPANDING",
    min_train_trades=3,
    initial_capital=10_000,
    position_size_percent=100,
    fee_bps=4,
    slippage_bps=2,
):
    db = SessionLocal()
    try:
        candles = get_latest_candles(db, symbol, timeframe, limit)
        result = run_walk_forward(
            candles,
            signal,
            stop_grid=stop_grid,
            target_grid=target_grid,
            train_size=train_size,
            test_size=test_size,
            step_size=step_size,
            mode=mode,
            min_train_trades=min_train_trades,
            initial_capital=initial_capital,
            position_size_percent=position_size_percent,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
        )
        result.update({"symbol": symbol, "timeframe": timeframe})
        return result
    finally:
        db.close()
