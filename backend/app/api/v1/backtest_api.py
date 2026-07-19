from fastapi import APIRouter, HTTPException, Query

from app.backtesting.phase2_validation_artifacts import load_phase2_validation_artifact
from app.backtesting.phase2_validation_artifacts import list_phase2_validation_artifacts
from app.backtesting.phase2_validation_artifacts import persist_phase2_validation_artifact
from app.backtesting.phase2_validation_artifacts import summarize_phase2_validation_artifacts
from app.backtesting.phase2_validation_report import build_phase2_validation_report
from app.backtesting.trade_simulator import execute_backtest, execute_filtered_backtest, execute_walk_forward
from app.backtesting.walk_forward_validator import PHASE2_OFFICIAL_TIMEFRAMES
from app.backtesting.walk_forward_validator import PHASE2_WALK_FORWARD_DAYS
from app.backtesting.walk_forward_validator import minimum_candles_for_folds
from app.backtesting.walk_forward_validator import phase2_walk_forward_defaults


router = APIRouter(prefix="/backtest", tags=["Backtesting"])


@router.get("/filtered-summary")
def filtered_backtest_summary(
    symbol: str,
    signal: str = Query(default="LONG", pattern="^(LONG|SHORT)$"),
    timeframe: str = Query(default="15m", pattern="^(1m|5m|15m|1h|4h|1d)$"),
    limit: int = Query(default=500, ge=51, le=5000),
    initial_capital: float = Query(default=10_000, gt=0),
    position_size_percent: float = Query(default=100, gt=0, le=100),
    min_confidence: float = Query(default=70, ge=0, le=100),
    stop_atr_multiple: float = Query(default=1.5, gt=0, le=20),
    target_atr_multiple: float = Query(default=3.5, gt=0, le=50),
    cooldown_candles: int = Query(default=3, ge=0, le=100),
    fee_bps: float = Query(default=4, ge=0, le=1000),
    slippage_bps: float = Query(default=2, ge=0, le=1000),
):
    return {
        "source": "filtered_backtest_summary_v2",
        "symbol": symbol,
        "signal": signal,
        "timeframe": timeframe,
        "result": execute_filtered_backtest(
            symbol,
            timeframe,
            signal,
            limit=limit,
            initial_capital=initial_capital,
            position_size_percent=position_size_percent,
            min_confidence=min_confidence,
            stop_atr_multiple=stop_atr_multiple,
            target_atr_multiple=target_atr_multiple,
            cooldown_candles=cooldown_candles,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
        ),
    }


@router.get("/walk-forward")
def walk_forward_validation(
    symbol: str,
    signal: str = Query(default="LONG", pattern="^(LONG|SHORT)$"),
    timeframe: str = Query(default="15m", pattern="^(1m|5m|15m|1h|4h|1d)$"),
    limit: int | None = Query(default=None, ge=3, le=10000),
    train_size: int | None = Query(default=None, ge=2, le=60000),
    test_size: int | None = Query(default=None, ge=1, le=30000),
    step_size: int | None = Query(default=None, ge=1, le=30000),
    mode: str = Query(default="EXPANDING", pattern="^(EXPANDING|ROLLING)$"),
    min_train_trades: int = Query(default=3, ge=1, le=1000),
    stop_grid: str = Query(default="0.75,1,1.25,1.5"),
    target_grid: str = Query(default="1.5,2,2.5,3"),
    initial_capital: float = Query(default=10_000, gt=0),
    position_size_percent: float = Query(default=100, gt=0, le=100),
    fee_bps: float = Query(default=4, ge=0, le=1000),
    slippage_bps: float = Query(default=2, ge=0, le=1000),
):
    resolved = _resolve_walk_forward_configuration(timeframe, limit, train_size, test_size, step_size)

    return {
        "source": "walk_forward_validation_v1",
        "symbol": symbol,
        "signal": signal,
        "timeframe": timeframe,
        "result": execute_walk_forward(
            symbol,
            timeframe,
            signal,
            limit=resolved["limit"],
            stop_grid=_parse_grid(stop_grid, "stop_grid"),
            target_grid=_parse_grid(target_grid, "target_grid"),
            train_size=resolved["train_size"],
            test_size=resolved["test_size"],
            step_size=resolved["step_size"],
            mode=mode,
            min_train_trades=min_train_trades,
            initial_capital=initial_capital,
            position_size_percent=position_size_percent,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
        ),
    }


@router.get("/phase2-report")
def phase2_validation_report(
    symbol: str,
    signal: str = Query(default="LONG", pattern="^(LONG|SHORT)$"),
    timeframe: str = Query(default="15m", pattern="^(1m|5m|15m|1h|4h|1d)$"),
    limit: int | None = Query(default=None, ge=3, le=10000),
    train_size: int | None = Query(default=None, ge=2, le=60000),
    test_size: int | None = Query(default=None, ge=1, le=30000),
    step_size: int | None = Query(default=None, ge=1, le=30000),
    mode: str = Query(default="EXPANDING", pattern="^(EXPANDING|ROLLING)$"),
    min_train_trades: int = Query(default=3, ge=1, le=1000),
    stop_grid: str = Query(default="0.75,1,1.25,1.5"),
    target_grid: str = Query(default="1.5,2,2.5,3"),
    initial_capital: float = Query(default=10_000, gt=0),
    position_size_percent: float = Query(default=100, gt=0, le=100),
    fee_bps: float = Query(default=4, ge=0, le=1000),
    slippage_bps: float = Query(default=2, ge=0, le=1000),
):
    resolved = _resolve_walk_forward_configuration(timeframe, limit, train_size, test_size, step_size)
    result = execute_walk_forward(
        symbol,
        timeframe,
        signal,
        limit=resolved["limit"],
        stop_grid=_parse_grid(stop_grid, "stop_grid"),
        target_grid=_parse_grid(target_grid, "target_grid"),
        train_size=resolved["train_size"],
        test_size=resolved["test_size"],
        step_size=resolved["step_size"],
        mode=mode,
        min_train_trades=min_train_trades,
        initial_capital=initial_capital,
        position_size_percent=position_size_percent,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
    )
    return {
        "source": "phase2_validation_report_v1",
        "symbol": symbol,
        "signal": signal,
        "timeframe": timeframe,
        "result": result,
        "report": build_phase2_validation_report(
            result,
            symbol=symbol,
            timeframe=timeframe,
            signal=signal,
        ),
    }


@router.post("/phase2-report/export")
def export_phase2_validation_report(
    symbol: str,
    signal: str = Query(default="LONG", pattern="^(LONG|SHORT)$"),
    timeframe: str = Query(default="15m", pattern="^(1m|5m|15m|1h|4h|1d)$"),
    limit: int | None = Query(default=None, ge=3, le=10000),
    train_size: int | None = Query(default=None, ge=2, le=60000),
    test_size: int | None = Query(default=None, ge=1, le=30000),
    step_size: int | None = Query(default=None, ge=1, le=30000),
    mode: str = Query(default="EXPANDING", pattern="^(EXPANDING|ROLLING)$"),
    min_train_trades: int = Query(default=3, ge=1, le=1000),
    stop_grid: str = Query(default="0.75,1,1.25,1.5"),
    target_grid: str = Query(default="1.5,2,2.5,3"),
    initial_capital: float = Query(default=10_000, gt=0),
    position_size_percent: float = Query(default=100, gt=0, le=100),
    fee_bps: float = Query(default=4, ge=0, le=1000),
    slippage_bps: float = Query(default=2, ge=0, le=1000),
):
    resolved = _resolve_walk_forward_configuration(timeframe, limit, train_size, test_size, step_size)
    result = execute_walk_forward(
        symbol,
        timeframe,
        signal,
        limit=resolved["limit"],
        stop_grid=_parse_grid(stop_grid, "stop_grid"),
        target_grid=_parse_grid(target_grid, "target_grid"),
        train_size=resolved["train_size"],
        test_size=resolved["test_size"],
        step_size=resolved["step_size"],
        mode=mode,
        min_train_trades=min_train_trades,
        initial_capital=initial_capital,
        position_size_percent=position_size_percent,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
    )
    report = build_phase2_validation_report(
        result,
        symbol=symbol,
        timeframe=timeframe,
        signal=signal,
    )
    artifact = persist_phase2_validation_artifact(
        report,
        result,
        symbol=symbol,
        timeframe=timeframe,
        signal=signal,
    )
    return {
        "source": "phase2_validation_export_v1",
        "report": report,
        "artifact": artifact,
    }


@router.get("/phase2-report/history")
def phase2_validation_history(
    symbol: str | None = Query(default=None),
    timeframe: str | None = Query(default=None, pattern="^(1m|5m|15m|1h|4h|1d)$"),
    signal: str | None = Query(default=None, pattern="^(LONG|SHORT)$"),
    limit: int = Query(default=10, ge=1, le=100),
):
    records = list_phase2_validation_artifacts(
        symbol=symbol,
        timeframe=timeframe,
        signal=signal,
        limit=limit,
    )
    return {
        "source": "phase2_validation_history_v1",
        "count": len(records),
        "records": records,
    }


@router.get("/phase2-report/artifact")
def get_phase2_validation_artifact(artifact_id: str):
    artifact = load_phase2_validation_artifact(artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Phase 2 validation artifact not found")
    return {
        "source": "phase2_validation_artifact_v1",
        **artifact,
    }


@router.get("/phase2-report/summary")
def phase2_validation_summary(
    symbol: str | None = Query(default=None),
    timeframe: str | None = Query(default=None, pattern="^(1m|5m|15m|1h|4h|1d)$"),
    signal: str | None = Query(default=None, pattern="^(LONG|SHORT)$"),
    limit: int = Query(default=20, ge=1, le=100),
):
    records = summarize_phase2_validation_artifacts(
        symbol=symbol,
        timeframe=timeframe,
        signal=signal,
        limit=limit,
    )
    return {
        "source": "phase2_validation_summary_v1",
        "count": len(records),
        "records": records,
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


def _resolve_walk_forward_configuration(timeframe, limit, train_size, test_size, step_size):
    timeframe_key = str(timeframe or "").strip()
    if timeframe_key in PHASE2_OFFICIAL_TIMEFRAMES:
        defaults = phase2_walk_forward_defaults(timeframe_key)
        resolved_train = int(train_size if train_size is not None else defaults["train_size"])
        resolved_test = int(test_size if test_size is not None else defaults["test_size"])
        resolved_step = int(step_size if step_size is not None else defaults["step_size"])
        resolved_limit = int(
            limit
            if limit is not None
            else minimum_candles_for_folds(
                resolved_train,
                resolved_test,
                resolved_step,
                PHASE2_WALK_FORWARD_DAYS["minimum_folds"],
            )
        )
    else:
        resolved_train = int(train_size if train_size is not None else 200)
        resolved_test = int(test_size if test_size is not None else 50)
        resolved_step = int(step_size if step_size is not None else 50)
        resolved_limit = int(limit if limit is not None else 1000)

    if resolved_step < resolved_test:
        raise HTTPException(
            status_code=422,
            detail="step_size must be at least test_size to prevent overlapping test folds",
        )
    if resolved_limit > 10000:
        resolved_limit = 10000

    return {
        "limit": resolved_limit,
        "train_size": resolved_train,
        "test_size": resolved_test,
        "step_size": resolved_step,
    }
