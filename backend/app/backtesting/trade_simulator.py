from bisect import bisect_right

from app.database.sqlserver import SessionLocal

from app.repositories.candle_repository import get_latest_candles

from app.backtesting.backtest_engine import run_backtest
from app.backtesting.filtered_replay_engine import run_filtered_replay
from app.backtesting.walk_forward_validator import run_walk_forward
from app.features.point_in_time_feature_service import build_point_in_time_bundle
from app.features.point_in_time_feature_service import build_features_as_of
from app.features.point_in_time_feature_service import build_feature_snapshot
from app.utils.freshness import normalize_timestamp_to_utc

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
    strategy="SIGNAL_GATED",
    min_confidence=70,
    cooldown_candles=3,
):
    db = SessionLocal()
    try:
        candles = get_latest_candles(db, symbol, timeframe, limit)
        # FastAPI supplies a raw string at runtime, while direct internal
        # callers may pass the Query default object unchanged.
        strategy_key = str(getattr(strategy, "default", strategy) or "SIGNAL_GATED").upper()
        if strategy_key not in {"SIGNAL_GATED", "BASELINE", "RESEARCH_CALIBRATION"}:
            raise ValueError("strategy must be SIGNAL_GATED, BASELINE, or RESEARCH_CALIBRATION")

        if strategy_key in {"SIGNAL_GATED", "RESEARCH_CALIBRATION"}:
            is_research = strategy_key == "RESEARCH_CALIBRATION"
            gate_profile = "RESEARCH_RELAXED" if is_research else "STRICT"
            effective_min_confidence = 60 if is_research else min_confidence
            feature_resolver = _build_in_memory_feature_resolver(
                symbol,
                timeframe,
                candles,
            )

            def backtest_runner(items, side, **options):
                return run_filtered_replay(
                    items,
                    side,
                    feature_resolver=feature_resolver,
                    initial_capital=options["initial_capital"],
                    position_size_percent=options["position_size_percent"],
                    min_confidence=effective_min_confidence,
                    stop_atr_multiple=options["stop_percent"],
                    target_atr_multiple=options["target_percent"],
                    cooldown_candles=cooldown_candles,
                    fee_bps=options["fee_bps"],
                    slippage_bps=options["slippage_bps"],
                    gate_profile=gate_profile,
                )

            strategy_name = (
                "CANDLE_RECONSTRUCTED_RESEARCH_GATE_V1"
                if is_research
                else "CANDLE_RECONSTRUCTED_REGIME_FILTER_V1"
            )
            strategy_metadata = {
                "mode": "RESEARCH_CALIBRATION" if is_research else "SIGNAL_GATED",
                "feature_source": "IN_MEMORY_POINT_IN_TIME_CANDLE_RECONSTRUCTION",
                "min_confidence": float(effective_min_confidence),
                "cooldown_candles": int(cooldown_candles),
                "gate_profile": gate_profile,
                "production_eligible": not is_research,
                "stop_parameter_model": "ATR_MULTIPLE",
                "target_parameter_model": "ATR_MULTIPLE",
            }
        else:
            backtest_runner = run_backtest
            strategy_name = "DIRECTIONAL_REENTRY_BASELINE"
            strategy_metadata = {
                "mode": "BASELINE",
                "feature_source": "NONE",
                "stop_parameter_model": "PERCENT",
                "target_parameter_model": "PERCENT",
            }

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
            backtest_runner=backtest_runner,
            strategy_name=strategy_name,
            strategy_metadata=strategy_metadata,
        )
        result.update({"symbol": symbol, "timeframe": timeframe})
        return result
    finally:
        db.close()


def _build_in_memory_feature_resolver(symbol, timeframe, candles, history_limit=300):
    """Build point-in-time features once per candle without per-candle DB queries."""
    ordered = sorted(
        [candle for candle in (candles or []) if getattr(candle, "candle_time", None) is not None],
        key=lambda candle: normalize_timestamp_to_utc(candle.candle_time),
    )
    timestamps = [normalize_timestamp_to_utc(candle.candle_time) for candle in ordered]
    cache = {}

    def resolve(as_of_timestamp):
        normalized_as_of = normalize_timestamp_to_utc(as_of_timestamp)
        if normalized_as_of is None:
            return None
        cache_key = normalized_as_of.isoformat()
        if cache_key in cache:
            return cache[cache_key]

        end_index = bisect_right(timestamps, normalized_as_of)
        if end_index <= 0:
            cache[cache_key] = None
            return None

        history = ordered[max(0, end_index - history_limit):end_index]
        feature_contract = build_feature_snapshot(
            symbol,
            timeframe,
            history,
            source_timestamp=as_of_timestamp,
            effective_timestamp=as_of_timestamp,
        )
        result = {
            **feature_contract,
            "_point_in_time": {
                "feature_source": "RECONSTRUCTED_FROM_CLOSED_CANDLES",
                "feature_snapshot_found": False,
                "decision_snapshot_found": False,
                "thesis_snapshot_found": False,
                "feature_leakage_status": "PASS",
                "thesis_leakage_status": "PARTIAL",
            },
        }
        cache[cache_key] = result
        return result

    return resolve
