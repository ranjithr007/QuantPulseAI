import json
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from sqlalchemy.exc import SQLAlchemyError
from app.contracts.backtest import BacktestResponse

from app.backtesting.phase2_validation_artifacts import load_phase2_validation_artifact
from app.backtesting.phase2_validation_artifacts import list_phase2_validation_artifacts
from app.backtesting.phase2_validation_artifacts import persist_phase2_validation_artifact
from app.backtesting.phase2_validation_artifacts import summarize_phase2_validation_artifacts
from app.backtesting.phase2_validation_report import build_phase2_validation_report
from app.backtesting.research_table_export import persist_cluster_research_tables
from app.backtesting.strategy_family_research import build_r5_strategy_evidence
from app.backtesting.trade_simulator import execute_backtest
from app.backtesting.trade_simulator import execute_collision_sensitivity_backtest
from app.backtesting.trade_simulator import execute_filtered_backtest
from app.backtesting.trade_simulator import execute_portfolio_backtest
from app.backtesting.trade_simulator import execute_walk_forward
from app.backtesting.walk_forward_validator import PHASE2_OFFICIAL_TIMEFRAMES
from app.backtesting.walk_forward_validator import PHASE2_WALK_FORWARD_DAYS
from app.backtesting.walk_forward_validator import minimum_candles_for_folds
from app.backtesting.walk_forward_validator import phase2_walk_forward_defaults
from app.backtesting.walk_forward_jobs import complete_walk_forward_job
from app.backtesting.walk_forward_jobs import create_walk_forward_job
from app.backtesting.walk_forward_jobs import fail_walk_forward_job
from app.backtesting.walk_forward_jobs import load_walk_forward_job
from app.backtesting.walk_forward_jobs import mark_walk_forward_job_running
from app.backtesting.walk_forward_jobs import public_walk_forward_job
from app.database.sqlserver import SessionLocal
from app.paper_trading.measurement import build_measurement_report
from app.paper_trading.measurement import attach_regime_outcome_context
from app.paper_trading.measurement import attach_scenario_context
from app.repositories.paper_trade_repository import PaperTradeRepository


router = APIRouter(prefix="/backtest", tags=["Backtesting"])
MAX_WALK_FORWARD_CANDLES = 20000
WALK_FORWARD_STRATEGIES = (
    "^(SIGNAL_GATED|BASELINE|RESEARCH_CALIBRATION|SHORT_EDGE_CALIBRATION|"
    "BEAR_RALLY_EXHAUSTION|PROFIT_PROTECTION_RESEARCH)$"
)


@router.get("/filtered-summary", response_model=BacktestResponse)
def filtered_backtest_summary(
    symbol: str,
    signal: str = Query(default="LONG", pattern="^(LONG|SHORT)$"),
    timeframe: str = Query(default="15m", pattern="^(1m|5m|15m|1h|2h|4h|1d)$"),
    limit: int = Query(default=500, ge=51, le=5000),
    initial_capital: float = Query(default=10_000, gt=0),
    position_size_percent: float = Query(default=100, gt=0, le=100),
    min_confidence: float = Query(default=70, ge=0, le=100),
    stop_atr_multiple: float = Query(default=1.5, gt=0, le=20),
    target_atr_multiple: float = Query(default=3.5, gt=0, le=50),
    cooldown_candles: int = Query(default=3, ge=0, le=100),
    fee_bps: float = Query(default=4, ge=0, le=1000),
    slippage_bps: float = Query(default=2, ge=0, le=1000),
    risk_percent_per_trade: float | None = Query(default=None, gt=0, le=100),
    target_trade_volatility_percent: float | None = Query(default=None, gt=0, le=100),
    max_leverage: float = Query(default=1, ge=1, le=20),
    max_open_positions: int = Query(default=20, ge=1, le=100),
    max_gross_exposure_percent: float = Query(default=500, gt=0, le=2000),
    initial_portfolio_json: str = Query(default="[]"),
    collision_policy: str = Query(
        default="STOP_FIRST",
        pattern="^(STOP_FIRST|TARGET_FIRST|LOWER_TIMEFRAME_REQUIRED)$",
    ),
):
    _validate_sizing_authority(
        risk_percent_per_trade,
        target_trade_volatility_percent,
    )
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
            risk_percent_per_trade=risk_percent_per_trade,
            target_trade_volatility_percent=target_trade_volatility_percent,
            max_leverage=max_leverage,
            max_open_positions=max_open_positions,
            max_gross_exposure_percent=max_gross_exposure_percent,
            initial_portfolio_positions=_parse_initial_portfolio(
                initial_portfolio_json
            ),
            collision_policy=collision_policy,
        ),
    }


@router.get("/portfolio-replay", response_model=BacktestResponse)
def portfolio_replay_report(
    symbols: str,
    signal: str = Query(default="LONG", pattern="^(LONG|SHORT)$"),
    timeframe: str = Query(default="1h", pattern="^(1h|2h|4h|1d)$"),
    limit: int = Query(default=500, ge=51, le=5000),
    initial_capital: float = Query(default=10_000, gt=0),
    position_size_percent: float = Query(default=25, gt=0, le=100),
    min_confidence: float = Query(default=70, ge=0, le=100),
    stop_atr_multiple: float = Query(default=1.5, gt=0, le=20),
    target_atr_multiple: float = Query(default=3.5, gt=0, le=50),
    cooldown_candles: int = Query(default=3, ge=0, le=100),
    fee_bps: float = Query(default=4, ge=0, le=1000),
    slippage_bps: float = Query(default=2, ge=0, le=1000),
    risk_percent_per_trade: float | None = Query(default=None, gt=0, le=100),
    target_trade_volatility_percent: float | None = Query(default=None, gt=0, le=100),
    max_leverage: float = Query(default=1, ge=1, le=20),
    max_open_positions: int = Query(default=5, ge=1, le=100),
    max_gross_exposure_percent: float = Query(default=300, gt=0, le=2000),
    max_cluster_exposure_percent: float = Query(default=150, gt=0, le=2000),
    symbol_clusters_json: str = Query(default="{}"),
    initial_portfolio_json: str = Query(default="[]"),
    collision_policy: str = Query(
        default="STOP_FIRST",
        pattern="^(STOP_FIRST|TARGET_FIRST|LOWER_TIMEFRAME_REQUIRED)$",
    ),
):
    _validate_sizing_authority(
        risk_percent_per_trade,
        target_trade_volatility_percent,
    )
    resolved_symbols = _parse_symbols(symbols)
    return {
        "source": "portfolio_replay_v1",
        "timeframe": timeframe,
        "signal": signal,
        "result": execute_portfolio_backtest(
            resolved_symbols,
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
            risk_percent_per_trade=risk_percent_per_trade,
            target_trade_volatility_percent=target_trade_volatility_percent,
            max_leverage=max_leverage,
            max_open_positions=max_open_positions,
            max_gross_exposure_percent=max_gross_exposure_percent,
            max_cluster_exposure_percent=max_cluster_exposure_percent,
            symbol_clusters=_parse_symbol_clusters(symbol_clusters_json),
            initial_portfolio_positions=_parse_initial_portfolio(
                initial_portfolio_json
            ),
            collision_policy=collision_policy,
        ),
    }


@router.post("/portfolio-research-export")
def export_portfolio_research_tables(payload: dict):
    portfolio_result = dict(payload.get("result") or payload)
    if portfolio_result.get("engine_version") != "portfolio_replay_v1":
        raise HTTPException(
            status_code=422,
            detail="payload must contain a portfolio_replay_v1 result",
        )
    if not isinstance(portfolio_result.get("trades"), list):
        raise HTTPException(
            status_code=422,
            detail="portfolio replay result must contain a trades array",
        )
    return {
        "source": "portfolio_research_export_v1",
        "artifact": persist_cluster_research_tables(portfolio_result),
    }


@router.post("/r5-strategy-evidence")
def r5_strategy_evidence(payload: dict):
    walk_forward_result = dict(payload.get("walk_forward_result") or {})
    if walk_forward_result.get("engine_version") != "walk_forward_v1":
        raise HTTPException(
            status_code=422,
            detail="walk_forward_result must contain a walk_forward_v1 result",
        )
    return {
        "source": "r5_strategy_family_evidence_v1",
        "result": build_r5_strategy_evidence(
            walk_forward_result,
            adverse_cost_result=payload.get("adverse_cost_result"),
            prior_baseline=payload.get("prior_baseline"),
        ),
    }


@router.get("/collision-sensitivity", response_model=BacktestResponse)
def collision_sensitivity_report(
    symbol: str,
    signal: str = Query(default="LONG", pattern="^(LONG|SHORT)$"),
    timeframe: str = Query(default="1h", pattern="^(1h|2h|4h|1d)$"),
    limit: int = Query(default=500, ge=51, le=5000),
    initial_capital: float = Query(default=10_000, gt=0),
    position_size_percent: float = Query(default=100, gt=0, le=100),
    min_confidence: float = Query(default=70, ge=0, le=100),
    stop_atr_multiple: float = Query(default=1.5, gt=0, le=20),
    target_atr_multiple: float = Query(default=3.5, gt=0, le=50),
    cooldown_candles: int = Query(default=3, ge=0, le=100),
    fee_bps: float = Query(default=4, ge=0, le=1000),
    slippage_bps: float = Query(default=2, ge=0, le=1000),
    risk_percent_per_trade: float | None = Query(default=None, gt=0, le=100),
    target_trade_volatility_percent: float | None = Query(default=None, gt=0, le=100),
    max_leverage: float = Query(default=1, ge=1, le=20),
    max_open_positions: int = Query(default=20, ge=1, le=100),
    max_gross_exposure_percent: float = Query(default=500, gt=0, le=2000),
    initial_portfolio_json: str = Query(default="[]"),
):
    _validate_sizing_authority(
        risk_percent_per_trade,
        target_trade_volatility_percent,
    )
    return {
        "source": "collision_sensitivity_v1",
        "symbol": symbol,
        "signal": signal,
        "timeframe": timeframe,
        "result": execute_collision_sensitivity_backtest(
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
            risk_percent_per_trade=risk_percent_per_trade,
            target_trade_volatility_percent=target_trade_volatility_percent,
            max_leverage=max_leverage,
            max_open_positions=max_open_positions,
            max_gross_exposure_percent=max_gross_exposure_percent,
            initial_portfolio_positions=_parse_initial_portfolio(
                initial_portfolio_json
            ),
        ),
    }


@router.get("/walk-forward", deprecated=True)
def retired_walk_forward_validation(
    symbol: str,
):
    del symbol
    raise HTTPException(
        status_code=410,
        detail={
            "code": "SYNCHRONOUS_WALK_FORWARD_RETIRED",
            "message": (
                "Synchronous walk-forward execution was retired to prevent "
                "gateway timeouts. Submit an asynchronous job instead."
            ),
            "submit_url": "/api/backtest/walk-forward/jobs",
            "method": "POST",
        },
    )


def walk_forward_validation(
    symbol: str,
    signal: str = Query(default="LONG", pattern="^(LONG|SHORT)$"),
    timeframe: str = Query(default="15m", pattern="^(1m|5m|15m|1h|2h|4h|1d)$"),
    limit: int | None = Query(default=None, ge=3, le=MAX_WALK_FORWARD_CANDLES),
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
    strategy: str = Query(default="SIGNAL_GATED", pattern=WALK_FORWARD_STRATEGIES),
    risk_percent_per_trade: float | None = Query(default=None, gt=0, le=100),
    target_trade_volatility_percent: float | None = Query(default=None, gt=0, le=100),
    max_leverage: float = Query(default=1, ge=1, le=20),
    max_open_positions: int = Query(default=20, ge=1, le=100),
    max_gross_exposure_percent: float = Query(default=500, gt=0, le=2000),
    initial_portfolio_json: str = Query(default="[]"),
    collision_policy: str = Query(
        default="STOP_FIRST",
        pattern="^(STOP_FIRST|TARGET_FIRST|LOWER_TIMEFRAME_REQUIRED)$",
    ),
    as_of: datetime | None = Query(default=None),
    frozen_fold_parameters_json: str = Query(default="[]"),
):
    """Run the calculation directly for trusted in-process callers only.

    The public HTTP route is intentionally retired; API clients must submit a
    persistent asynchronous job through ``POST /walk-forward/jobs``.
    """
    _validate_sizing_authority(
        risk_percent_per_trade,
        target_trade_volatility_percent,
    )
    resolved = _resolve_walk_forward_configuration(
        timeframe,
        limit,
        train_size,
        test_size,
        step_size,
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
            strategy=strategy,
            risk_percent_per_trade=risk_percent_per_trade,
            target_trade_volatility_percent=target_trade_volatility_percent,
            max_leverage=max_leverage,
            max_open_positions=max_open_positions,
            max_gross_exposure_percent=max_gross_exposure_percent,
            initial_portfolio_positions=_parse_initial_portfolio(
                initial_portfolio_json
            ),
            collision_policy=collision_policy,
            **_as_of_options(as_of),
            **_frozen_fold_options(frozen_fold_parameters_json),
        ),
    }


@router.post("/walk-forward/jobs", status_code=202)
def submit_walk_forward_validation_job(
    background_tasks: BackgroundTasks,
    symbol: str,
    signal: str = Query(default="LONG", pattern="^(LONG|SHORT)$"),
    timeframe: str = Query(default="1h", pattern="^(1h|2h|4h|1d)$"),
    limit: int | None = Query(default=None, ge=3, le=MAX_WALK_FORWARD_CANDLES),
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
    strategy: str = Query(default="SIGNAL_GATED", pattern=WALK_FORWARD_STRATEGIES),
    risk_percent_per_trade: float | None = Query(default=None, gt=0, le=100),
    target_trade_volatility_percent: float | None = Query(default=None, gt=0, le=100),
    max_leverage: float = Query(default=1, ge=1, le=20),
    max_open_positions: int = Query(default=20, ge=1, le=100),
    max_gross_exposure_percent: float = Query(default=500, gt=0, le=2000),
    initial_portfolio_json: str = Query(default="[]"),
    collision_policy: str = Query(
        default="STOP_FIRST",
        pattern="^(STOP_FIRST|TARGET_FIRST|LOWER_TIMEFRAME_REQUIRED)$",
    ),
    as_of: datetime | None = Query(default=None),
    frozen_fold_parameters_json: str = Query(default="[]"),
):
    _validate_sizing_authority(
        risk_percent_per_trade,
        target_trade_volatility_percent,
    )
    resolved = _resolve_walk_forward_configuration(
        timeframe,
        limit,
        train_size,
        test_size,
        step_size,
    )
    parameters = {
        "symbol": str(symbol).upper(),
        "timeframe": timeframe,
        "signal": signal,
        "limit": resolved["limit"],
        "stop_grid": _parse_grid(stop_grid, "stop_grid"),
        "target_grid": _parse_grid(target_grid, "target_grid"),
        "train_size": resolved["train_size"],
        "test_size": resolved["test_size"],
        "step_size": resolved["step_size"],
        "mode": mode,
        "min_train_trades": min_train_trades,
        "initial_capital": initial_capital,
        "position_size_percent": position_size_percent,
        "fee_bps": fee_bps,
        "slippage_bps": slippage_bps,
        "strategy": strategy,
        "risk_percent_per_trade": risk_percent_per_trade,
        "target_trade_volatility_percent": target_trade_volatility_percent,
        "max_leverage": max_leverage,
        "max_open_positions": max_open_positions,
        "max_gross_exposure_percent": max_gross_exposure_percent,
        "initial_portfolio_positions": _parse_initial_portfolio(
            initial_portfolio_json
        ),
        "collision_policy": collision_policy,
        **_as_of_options(as_of),
        **_frozen_fold_options(frozen_fold_parameters_json),
    }
    record, created = create_walk_forward_job(parameters)
    if created:
        background_tasks.add_task(
            _run_walk_forward_validation_job,
            record["job_id"],
            parameters,
        )
    return public_walk_forward_job(record)


@router.get("/walk-forward/jobs/{job_id}")
def get_walk_forward_validation_job(job_id: str):
    try:
        record = load_walk_forward_job(job_id)
    except ValueError:
        record = None
    if record is None:
        raise HTTPException(status_code=404, detail="Walk-forward job not found")
    return public_walk_forward_job(record)


def _run_walk_forward_validation_job(job_id, parameters):
    mark_walk_forward_job_running(job_id)
    try:
        result = execute_walk_forward(**parameters)
        symbol = parameters["symbol"]
        timeframe = parameters["timeframe"]
        signal = parameters["signal"]
        response = {
            "source": "walk_forward_validation_v1",
            "symbol": symbol,
            "signal": signal,
            "timeframe": timeframe,
            "result": result,
            "report": build_phase2_validation_report(
                result,
                symbol=symbol,
                timeframe=timeframe,
                signal=signal,
                paper_measurement=_load_paper_measurement(symbol),
            ),
        }
        complete_walk_forward_job(job_id, response)
    except Exception as exc:
        fail_walk_forward_job(job_id, exc)


@router.get("/phase2-report")
def phase2_validation_report(
    symbol: str,
    signal: str = Query(default="LONG", pattern="^(LONG|SHORT)$"),
    timeframe: str = Query(default="15m", pattern="^(1m|5m|15m|1h|2h|4h|1d)$"),
    limit: int | None = Query(default=None, ge=3, le=MAX_WALK_FORWARD_CANDLES),
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
    strategy: str = Query(default="SIGNAL_GATED", pattern=WALK_FORWARD_STRATEGIES),
    as_of: datetime | None = Query(default=None),
    frozen_fold_parameters_json: str = Query(default="[]"),
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
        strategy=strategy,
        **_as_of_options(as_of),
        **_frozen_fold_options(frozen_fold_parameters_json),
    )
    paper_measurement = _load_paper_measurement(symbol)
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
            paper_measurement=paper_measurement,
        ),
    }


@router.post("/phase2-report/export")
def export_phase2_validation_report(
    symbol: str,
    signal: str = Query(default="LONG", pattern="^(LONG|SHORT)$"),
    timeframe: str = Query(default="15m", pattern="^(1m|5m|15m|1h|2h|4h|1d)$"),
    limit: int | None = Query(default=None, ge=3, le=MAX_WALK_FORWARD_CANDLES),
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
    strategy: str = Query(default="SIGNAL_GATED", pattern=WALK_FORWARD_STRATEGIES),
    as_of: datetime | None = Query(default=None),
    frozen_fold_parameters_json: str = Query(default="[]"),
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
        strategy=strategy,
        **_as_of_options(as_of),
        **_frozen_fold_options(frozen_fold_parameters_json),
    )
    report = build_phase2_validation_report(
        result,
        symbol=symbol,
        timeframe=timeframe,
        signal=signal,
        paper_measurement=_load_paper_measurement(symbol),
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
    timeframe: str | None = Query(default=None, pattern="^(1m|5m|15m|1h|2h|4h|1d)$"),
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
    timeframe: str | None = Query(default=None, pattern="^(1m|5m|15m|1h|2h|4h|1d)$"),
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


@router.get("/summary", response_model=BacktestResponse)
def backtest_summary(
    symbol: str,
    signal: str = Query(default="LONG", pattern="^(LONG|SHORT)$"),
    timeframe: str = Query(default="15m", pattern="^(1m|5m|15m|1h|2h|4h|1d)$"),
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
    # Route functions are also invoked directly by tests/internal callers,
    # where FastAPI has not replaced Query defaults with their raw values.
    value = _query_default(value)
    try:
        values = [float(item.strip()) for item in str(value).split(",") if item.strip()]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{name} must be comma-separated numbers") from exc
    if not values or any(item <= 0 for item in values):
        raise HTTPException(status_code=422, detail=f"{name} must contain positive numbers")
    if len(values) > 20:
        raise HTTPException(status_code=422, detail=f"{name} cannot contain more than 20 values")
    return values


def _validate_sizing_authority(
    risk_percent_per_trade,
    target_trade_volatility_percent,
):
    risk_percent_per_trade = _query_default(risk_percent_per_trade)
    target_trade_volatility_percent = _query_default(
        target_trade_volatility_percent
    )
    if (
        risk_percent_per_trade is not None
        and target_trade_volatility_percent is not None
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "risk_percent_per_trade and target_trade_volatility_percent "
                "are mutually exclusive"
            ),
        )


def _parse_initial_portfolio(value):
    value = _query_default(value)
    try:
        payload = json.loads(str(value or "[]"))
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=422,
            detail="initial_portfolio_json must be valid JSON",
        ) from exc
    if not isinstance(payload, list) or any(
        not isinstance(item, dict)
        for item in payload
    ):
        raise HTTPException(
            status_code=422,
            detail="initial_portfolio_json must be a JSON array of positions",
        )
    return payload


def _parse_symbols(value):
    symbols = []
    for raw_symbol in str(_query_default(value) or "").split(","):
        symbol = raw_symbol.strip().upper()
        if symbol and symbol not in symbols:
            symbols.append(symbol)
    if len(symbols) < 2:
        raise HTTPException(
            status_code=422,
            detail="portfolio replay requires at least two unique symbols",
        )
    if len(symbols) > 20:
        raise HTTPException(
            status_code=422,
            detail="portfolio replay supports at most 20 symbols",
        )
    return symbols


def _parse_symbol_clusters(value):
    value = _query_default(value)
    try:
        payload = json.loads(str(value or "{}"))
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=422,
            detail="symbol_clusters_json must be valid JSON",
        ) from exc
    if not isinstance(payload, dict) or any(
        not str(symbol).strip() or not str(cluster).strip()
        for symbol, cluster in payload.items()
    ):
        raise HTTPException(
            status_code=422,
            detail="symbol_clusters_json must be a JSON object of symbol to cluster",
        )
    return {
        str(symbol).upper(): str(cluster)
        for symbol, cluster in payload.items()
    }


def _as_of_options(value):
    value = _query_default(value)
    return {"as_of_timestamp": value} if value is not None else {}


def _frozen_fold_options(value):
    value = _query_default(value)
    try:
        payload = json.loads(str(value or "[]"))
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=422,
            detail="frozen_fold_parameters_json must be valid JSON",
        ) from exc
    if not isinstance(payload, list):
        raise HTTPException(
            status_code=422,
            detail="frozen_fold_parameters_json must be a JSON array",
        )
    normalized = []
    for item in payload:
        if not isinstance(item, dict) or {
            "stop_percent",
            "target_percent",
        } - set(item):
            raise HTTPException(
                status_code=422,
                detail=(
                    "each frozen fold parameter requires stop_percent "
                    "and target_percent"
                ),
            )
        try:
            stop = float(item["stop_percent"])
            target = float(item["target_percent"])
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=422,
                detail="frozen fold parameters must be numeric",
            ) from exc
        if stop <= 0 or target <= 0:
            raise HTTPException(
                status_code=422,
                detail="frozen fold parameters must be greater than zero",
            )
        normalized.append(
            {
                "stop_percent": stop,
                "target_percent": target,
            }
        )
    return {"frozen_fold_parameters": normalized} if normalized else {}


def _resolve_walk_forward_configuration(timeframe, limit, train_size, test_size, step_size):
    # Route functions are also called directly by unit tests and internal jobs;
    # unwrap FastAPI Query defaults when dependency injection is not involved.
    limit = _query_default(limit)
    train_size = _query_default(train_size)
    test_size = _query_default(test_size)
    step_size = _query_default(step_size)
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
    if resolved_limit > MAX_WALK_FORWARD_CANDLES:
        resolved_limit = MAX_WALK_FORWARD_CANDLES

    return {
        "limit": resolved_limit,
        "train_size": resolved_train,
        "test_size": resolved_test,
        "step_size": resolved_step,
    }


def _query_default(value):
    return getattr(value, "default", value)


def _load_paper_measurement(symbol):
    """Attach read-only paper evidence to Phase 2 reports when available."""
    db = SessionLocal()
    try:
        trades = PaperTradeRepository().all_trades(db, symbol=str(symbol or "").upper())
        attach_scenario_context(db, trades)
        attach_regime_outcome_context(db, trades)
        # Phase 2 evidence is scoped to the official entry stack. Legacy 5m/
        # 15m trades remain visible in the paper-trade ledger but cannot be
        # used to claim evidence for the current 1h/2h/4h/1d strategy.
        trades = [
            trade
            for trade in trades
            if str(getattr(trade, "entry_timeframe", "") or "").strip() in PHASE2_OFFICIAL_TIMEFRAMES
        ]
        report = build_measurement_report(trades)
        report["evidence_scope"] = {
            "market": "FUTURES",
            "mode": "intraday",
            "entry_timeframes": sorted(PHASE2_OFFICIAL_TIMEFRAMES),
            "excluded_legacy_timeframes": ["5m", "15m"],
        }
        return report
    except SQLAlchemyError:
        try:
            db.rollback()
        except Exception:
            pass
        return None
    finally:
        db.close()
