from fastapi import APIRouter, HTTPException, Query

from app.backtesting.trade_simulator import execute_backtest, execute_walk_forward


router = APIRouter(prefix="/backtest", tags=["Backtesting"])


@router.get("/walk-forward")
def walk_forward_validation(
    symbol: str,
    signal: str = Query(default="LONG", pattern="^(LONG|SHORT)$"),
    timeframe: str = Query(default="15m", pattern="^(1m|5m|15m|1h|4h|1d)$"),
    limit: int = Query(default=1000, ge=3, le=10000),
    train_size: int = Query(default=200, ge=2, le=5000),
    test_size: int = Query(default=50, ge=1, le=2000),
    step_size: int = Query(default=50, ge=1, le=2000),
    mode: str = Query(default="EXPANDING", pattern="^(EXPANDING|ROLLING)$"),
    min_train_trades: int = Query(default=3, ge=1, le=1000),
    stop_grid: str = Query(default="0.75,1,1.25,1.5"),
    target_grid: str = Query(default="1.5,2,2.5,3"),
    initial_capital: float = Query(default=10_000, gt=0),
    position_size_percent: float = Query(default=100, gt=0, le=100),
    fee_bps: float = Query(default=4, ge=0, le=1000),
    slippage_bps: float = Query(default=2, ge=0, le=1000),
):
    if step_size < test_size:
        raise HTTPException(
            status_code=422,
            detail="step_size must be at least test_size to prevent overlapping test folds",
        )

    return {
        "source": "walk_forward_validation_v1",
        "symbol": symbol,
        "signal": signal,
        "timeframe": timeframe,
        "result": execute_walk_forward(
            symbol,
            timeframe,
            signal,
            limit=limit,
            stop_grid=_parse_grid(stop_grid, "stop_grid"),
            target_grid=_parse_grid(target_grid, "target_grid"),
            train_size=train_size,
            test_size=test_size,
            step_size=step_size,
            mode=mode,
            min_train_trades=min_train_trades,
            initial_capital=initial_capital,
            position_size_percent=position_size_percent,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
        ),
    }


@router.post("/{symbol}")
def backtest(symbol: str, signal: str):

    return execute_backtest(symbol, "15m", None, signal)


@router.get("/summary")
def backtest_summary(
    symbol: str,
    signal: str = Query(default="LONG", pattern="^(LONG|SHORT)$"),
    timeframe: str = Query(default="15m", pattern="^(1m|5m|15m|1h|4h|1d)$"),
    limit: int = Query(default=500, ge=2, le=5000),
    initial_capital: float = Query(default=10_000, gt=0),
    position_size_percent: float = Query(default=100, gt=0, le=100),
    stop_percent: float = Query(default=1, gt=0, le=50),
    target_percent: float = Query(default=2, gt=0, le=100),
    fee_bps: float = Query(default=4, ge=0, le=1000),
    slippage_bps: float = Query(default=2, ge=0, le=1000),
):
    result = execute_backtest(
        symbol,
        timeframe,
        None,
        signal,
        limit=limit,
        initial_capital=initial_capital,
        position_size_percent=position_size_percent,
        stop_percent=stop_percent,
        target_percent=target_percent,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
    )

    return {
        "source": "backtest_summary_v2",
        "symbol": symbol,
        "signal": signal,
        "timeframe": timeframe,
        "result": result,
    }


def _parse_grid(value, name):
    try:
        values = [float(item.strip()) for item in str(value).split(",") if item.strip()]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{name} must be comma-separated numbers") from exc
    if not values or any(item <= 0 for item in values):
        raise HTTPException(status_code=422, detail=f"{name} must contain positive numbers")
    if len(values) > 20:
        raise HTTPException(status_code=422, detail=f"{name} cannot contain more than 20 values")
    return values
