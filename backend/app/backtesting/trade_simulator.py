from app.database.sqlserver import SessionLocal

from app.repositories.candle_repository import get_latest_candles

from app.backtesting.backtest_engine import run_backtest
from app.backtesting.filtered_replay_engine import run_filtered_replay
from app.backtesting.walk_forward_validator import run_walk_forward
from app.features.point_in_time_feature_service import build_point_in_time_bundle
from app.features.point_in_time_feature_service import build_features_as_of

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


def execute_filtered_backtest(
    symbol,
    timeframe,
    signal,
    *,
    limit=500,
    initial_capital=10_000,
    position_size_percent=100,
    min_confidence=70,
    stop_atr_multiple=1.5,
    target_atr_multiple=3.5,
    cooldown_candles=3,
    fee_bps=4,
    slippage_bps=2,
):
    db = SessionLocal()
    try:
        candles = get_latest_candles(db, symbol, timeframe, limit)
        def feature_resolver(as_of_timestamp):
            bundle = build_point_in_time_bundle(db, symbol, timeframe, as_of_timestamp)
            feature_contract = (
                (bundle.get("serialized") or {}).get("feature_snapshot")
                or build_features_as_of(
                    db,
                    symbol,
                    timeframe,
                    as_of_timestamp,
                    limit=limit,
                )
            )
            if not isinstance(feature_contract, dict):
                return feature_contract

            return {
                **feature_contract,
                "_point_in_time": {
                    "feature_source": (
                        "SNAPSHOT"
                        if bundle.get("feature_snapshot") is not None
                        else "RECONSTRUCTED_FALLBACK"
                    ),
                    "feature_snapshot_found": bundle.get("feature_snapshot") is not None,
                    "decision_snapshot_found": bundle.get("decision_snapshot") is not None,
                    "thesis_snapshot_found": bundle.get("thesis_snapshot") is not None,
                    "feature_leakage_status": ((bundle.get("feature_leakage_diagnostics") or {}).get("status")),
                    "thesis_leakage_status": ((bundle.get("thesis_leakage_diagnostics") or {}).get("status")),
                },
            }

        result = run_filtered_replay(
            candles,
            signal,
            feature_resolver=feature_resolver,
            initial_capital=initial_capital,
            position_size_percent=position_size_percent,
            min_confidence=min_confidence,
            stop_atr_multiple=stop_atr_multiple,
            target_atr_multiple=target_atr_multiple,
            cooldown_candles=cooldown_candles,
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
            timeframe=timeframe,
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
