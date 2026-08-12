from bisect import bisect_right
from math import ceil
from types import SimpleNamespace

from app.database.sqlserver import SessionLocal

from app.repositories.candle_repository import get_latest_candles
from app.repositories.candle_repository import get_candles_as_of

from app.backtesting.backtest_engine import run_backtest
from app.backtesting.filtered_replay_engine import run_filtered_replay
from app.backtesting.portfolio_replay import build_portfolio_replay
from app.backtesting.research_table_export import build_cluster_research_tables
from app.backtesting.walk_forward_validator import run_walk_forward
from app.backtesting.walk_forward_validator import TIMEFRAME_MINUTES
from app.backtesting.replay_contract import build_point_in_time_stack
from app.backtesting.point_in_time_intelligence import (
    build_stateful_intelligence_timeline,
    resolve_intelligence_timeline,
)
from app.backtesting.replay_derivatives import build_derivatives_as_of
from app.backtesting.replay_decision_chain import build_replay_decision_chain
from app.intelligence.master_ai_engine import generate_master_signal
from app.governance.evidence_policy import MIN_ENTRY_CONFIDENCE
from app.governance.evidence_policy import OFFICIAL_ENTRY_TIMEFRAMES
from app.features.point_in_time_feature_service import build_point_in_time_bundle
from app.features.point_in_time_feature_service import build_features_as_of
from app.features.point_in_time_feature_service import build_feature_snapshot
from app.utils.freshness import normalize_timestamp_to_utc
from app.repositories.derivative_repository import DerivativeRepository
from app.smc.smc_engine import analyze_smc

COLLISION_POLICIES = (
    "STOP_FIRST",
    "TARGET_FIRST",
    "LOWER_TIMEFRAME_REQUIRED",
)

# A fixed-cutoff baseline and its adverse-cost replay share the same immutable
# historical context. Keep only a small bounded cache so live/latest requests
# are never allowed to retain stale market data indefinitely.
_FROZEN_REPLAY_CONTEXT_CACHE = {}
_FROZEN_REPLAY_CONTEXT_CACHE_MAX = 2


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
    min_confidence=MIN_ENTRY_CONFIDENCE,
    stop_atr_multiple=1.5,
    target_atr_multiple=3.5,
    cooldown_candles=3,
    fee_bps=4,
    slippage_bps=2,
    risk_percent_per_trade=None,
    target_trade_volatility_percent=None,
    max_leverage=1,
    max_open_positions=20,
    max_gross_exposure_percent=500,
    initial_portfolio_positions=None,
    collision_policy="STOP_FIRST",
):
    db = SessionLocal()
    try:
        candles, feature_resolver, stack_resolver, derivative_history = (
            _build_filtered_replay_inputs(
            db,
            symbol,
            timeframe,
            limit,
            )
        )

        result = run_filtered_replay(
            candles,
            signal,
            feature_resolver=feature_resolver,
            stack_resolver=stack_resolver,
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
            initial_portfolio_positions=initial_portfolio_positions,
            collision_policy=collision_policy,
            timeframe_minutes=TIMEFRAME_MINUTES.get(timeframe, 60),
            mark_price_records=derivative_history.get("mark_prices"),
        )
        result.update({"symbol": symbol, "timeframe": timeframe})
        return result
    finally:
        db.close()


def execute_portfolio_backtest(
    symbols,
    timeframe,
    signal,
    *,
    limit=500,
    initial_capital=10_000,
    position_size_percent=25,
    min_confidence=MIN_ENTRY_CONFIDENCE,
    stop_atr_multiple=1.5,
    target_atr_multiple=3.5,
    cooldown_candles=3,
    fee_bps=4,
    slippage_bps=2,
    risk_percent_per_trade=None,
    target_trade_volatility_percent=None,
    max_leverage=1,
    max_open_positions=5,
    max_gross_exposure_percent=300,
    max_cluster_exposure_percent=150,
    symbol_clusters=None,
    initial_portfolio_positions=None,
    collision_policy="STOP_FIRST",
):
    symbol_results = {}
    for symbol in symbols:
        symbol_key = str(symbol).upper()
        symbol_results[symbol_key] = execute_filtered_backtest(
            symbol_key,
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
            max_open_positions=100,
            max_gross_exposure_percent=10_000,
            initial_portfolio_positions=[],
            collision_policy=collision_policy,
        )
    result = build_portfolio_replay(
        symbol_results,
        initial_capital=initial_capital,
        max_open_positions=max_open_positions,
        max_gross_exposure_percent=max_gross_exposure_percent,
        max_cluster_exposure_percent=max_cluster_exposure_percent,
        symbol_clusters=symbol_clusters,
        initial_positions=initial_portfolio_positions,
    )
    result.update(
        {
            "symbols": sorted(symbol_results),
            "timeframe": timeframe,
            "signal": str(signal).upper(),
            "candidate_replay_versions": {
                symbol: replay.get("engine_version")
                for symbol, replay in sorted(symbol_results.items())
            },
        }
    )
    result["research_export"] = build_cluster_research_tables(result)
    return result


def execute_collision_sensitivity_backtest(
    symbol,
    timeframe,
    signal,
    *,
    limit=500,
    initial_capital=10_000,
    position_size_percent=100,
    min_confidence=MIN_ENTRY_CONFIDENCE,
    stop_atr_multiple=1.5,
    target_atr_multiple=3.5,
    cooldown_candles=3,
    fee_bps=4,
    slippage_bps=2,
    risk_percent_per_trade=None,
    target_trade_volatility_percent=None,
    max_leverage=1,
    max_open_positions=20,
    max_gross_exposure_percent=500,
    initial_portfolio_positions=None,
):
    db = SessionLocal()
    try:
        candles, feature_resolver, stack_resolver, derivative_history = (
            _build_filtered_replay_inputs(
            db,
            symbol,
            timeframe,
            limit,
            )
        )
        policy_results = {}
        for policy in COLLISION_POLICIES:
            policy_results[policy] = run_filtered_replay(
                candles,
                signal,
                feature_resolver=feature_resolver,
                stack_resolver=stack_resolver,
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
                initial_portfolio_positions=initial_portfolio_positions,
                collision_policy=policy,
                timeframe_minutes=TIMEFRAME_MINUTES.get(timeframe, 60),
                mark_price_records=derivative_history.get("mark_prices"),
            )

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "signal": str(signal).upper(),
            **build_collision_sensitivity_report(policy_results),
        }
    finally:
        db.close()


def build_collision_sensitivity_report(policy_results):
    baseline = dict(policy_results.get("STOP_FIRST") or {})
    baseline_return = float(baseline.get("total_return_percent") or 0)
    metrics = []
    for policy in COLLISION_POLICIES:
        result = dict(policy_results.get(policy) or {})
        total_return = float(result.get("total_return_percent") or 0)
        trades = list(result.get("trades") or [])
        metrics.append(
            {
                "policy": policy,
                "total_trades": int(result.get("total_trades") or 0),
                "wins": int(result.get("wins") or 0),
                "losses": int(result.get("losses") or 0),
                "win_rate": result.get("win_rate"),
                "profit_factor": result.get("profit_factor"),
                "total_return_percent": result.get("total_return_percent"),
                "max_drawdown_percent": result.get("max_drawdown_percent"),
                "expectancy_percent": result.get("expectancy_percent"),
                "sharpe_ratio": result.get("sharpe_ratio"),
                "same_candle_collisions": sum(
                    1 for trade in trades if trade.get("intrabar_collision")
                ),
                "ambiguous_collision_exits": sum(
                    1
                    for trade in trades
                    if trade.get("exit_reason") == "AMBIGUOUS_COLLISION"
                ),
                "return_delta_vs_stop_first": round(
                    total_return - baseline_return,
                    4,
                ),
            }
        )

    returns = [
        float(item.get("total_return_percent") or 0)
        for item in metrics
    ]
    return {
        "baseline_policy": "STOP_FIRST",
        "production_policy_unchanged": True,
        "research_only": True,
        "policies": metrics,
        "sensitivity": {
            "return_range_percent": round(max(returns) - min(returns), 4),
            "outcome_sensitive": len(set(returns)) > 1,
        },
        "interpretation": (
            "A material return range indicates that candle-only collision ordering "
            "affects the result; use lower-timeframe or tick data before promotion."
        ),
    }


def _build_filtered_replay_inputs(db, symbol, timeframe, limit):
    candles = get_latest_candles(db, symbol, timeframe, limit)
    derivative_history = DerivativeRepository().history_through(
        db,
        symbol,
        _latest_candle_timestamp(candles),
        mark_price_timeframe=timeframe,
    )
    stack_resolver = _build_in_memory_stack_resolver(
        symbol,
        _load_replay_stack_candles(db, symbol, timeframe, candles, limit),
        derivative_history=derivative_history,
    )
    feature_cache = {}

    def feature_resolver(as_of_timestamp):
        cache_key = normalize_timestamp_to_utc(as_of_timestamp)
        if cache_key in feature_cache:
            return feature_cache[cache_key]

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
        if isinstance(feature_contract, dict):
            feature_contract = {
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
                    "feature_leakage_status": (
                        (bundle.get("feature_leakage_diagnostics") or {}).get("status")
                    ),
                    "thesis_leakage_status": (
                        (bundle.get("thesis_leakage_diagnostics") or {}).get("status")
                    ),
                },
            }
        feature_cache[cache_key] = feature_contract
        return feature_contract

    return candles, feature_resolver, stack_resolver, derivative_history


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
    min_confidence=MIN_ENTRY_CONFIDENCE,
    cooldown_candles=3,
    risk_percent_per_trade=None,
    target_trade_volatility_percent=None,
    max_leverage=1,
    max_open_positions=20,
    max_gross_exposure_percent=500,
    initial_portfolio_positions=None,
    collision_policy="STOP_FIRST",
    as_of_timestamp=None,
    frozen_fold_parameters=None,
    replay_context=None,
    regime_detector=None,
    transition_policy=None,
    research_label=None,
    research_gate_profile=None,
    risk_min_confidence=None,
    risk_confidence_scope=None,
):
    db = SessionLocal() if replay_context is None else None
    try:
        normalized_as_of = normalize_timestamp_to_utc(as_of_timestamp)
        if replay_context is not None:
            candles = replay_context["candles"]
        else:
            candles = (
                get_candles_as_of(
                    db,
                    symbol,
                    timeframe,
                    normalized_as_of,
                    limit,
                )
                if normalized_as_of is not None
                else get_latest_candles(db, symbol, timeframe, limit)
            )
        # FastAPI supplies a raw string at runtime, while direct internal
        # callers may pass the Query default object unchanged.
        strategy_key = str(getattr(strategy, "default", strategy) or "SIGNAL_GATED").upper()
        if strategy_key not in {
            "SIGNAL_GATED",
            "BASELINE",
            "RESEARCH_CALIBRATION",
            "SHORT_EDGE_CALIBRATION",
            "BEAR_RALLY_EXHAUSTION",
            "PROFIT_PROTECTION_RESEARCH",
        }:
            raise ValueError(
                "strategy must be SIGNAL_GATED, BASELINE, "
                "RESEARCH_CALIBRATION, SHORT_EDGE_CALIBRATION, "
                "BEAR_RALLY_EXHAUSTION, or PROFIT_PROTECTION_RESEARCH"
            )

        if strategy_key in {
            "SIGNAL_GATED",
            "RESEARCH_CALIBRATION",
            "SHORT_EDGE_CALIBRATION",
            "BEAR_RALLY_EXHAUSTION",
            "PROFIT_PROTECTION_RESEARCH",
        }:
            detector_research = (
                regime_detector is not None
                or transition_policy is not None
                or risk_min_confidence is not None
                or risk_confidence_scope is not None
            )
            is_research = strategy_key != "SIGNAL_GATED" or detector_research
            gate_profile = {
                "SIGNAL_GATED": "STRICT",
                "RESEARCH_CALIBRATION": "RESEARCH_RELAXED",
                "SHORT_EDGE_CALIBRATION": "SHORT_EDGE_RESEARCH",
                "BEAR_RALLY_EXHAUSTION": "BEAR_RALLY_EXHAUSTION_RESEARCH",
                "PROFIT_PROTECTION_RESEARCH": "RESEARCH_RELAXED",
            }[strategy_key]
            if research_gate_profile is not None:
                requested_research_profile = str(research_gate_profile).upper()
                if not detector_research or not requested_research_profile.endswith(
                    "_RESEARCH"
                ):
                    raise ValueError(
                        "research_gate_profile requires an injected research "
                        "detector/policy and a *_RESEARCH profile"
                    )
                gate_profile = requested_research_profile
            profit_protection_mode = (
                "BREAKEVEN_AFTER_R"
                if strategy_key == "PROFIT_PROTECTION_RESEARCH"
                else "NONE"
            )
            effective_min_confidence = (
                60 if strategy_key != "SIGNAL_GATED" else min_confidence
            )
            regime_detector_key = getattr(
                regime_detector,
                "__name__",
                "detect_regime",
            )
            transition_policy_key = getattr(
                transition_policy,
                "__name__",
                "production_hysteresis",
            )
            risk_min_confidence_key = (
                "production_40"
                if risk_min_confidence is None
                else f"research_{float(risk_min_confidence):g}"
            )
            risk_confidence_scope_key = str(
                risk_confidence_scope or "PRODUCTION_ALL"
            ).upper()
            context_key = (
                *_frozen_replay_context_key(
                    symbol,
                    timeframe,
                    limit,
                    normalized_as_of,
                ),
                regime_detector_key,
                transition_policy_key,
                risk_min_confidence_key,
                risk_confidence_scope_key,
            )
            context = replay_context.get("_runtime") if replay_context is not None else (
                _FROZEN_REPLAY_CONTEXT_CACHE.get(context_key)
                if normalized_as_of is not None
                else None
            )
            if context is None:
                if replay_context is not None:
                    derivative_history = replay_context["derivative_history"]
                    stack_candles = replay_context["stack_candles"]
                else:
                    derivative_history = DerivativeRepository().history_through(
                        db,
                        symbol,
                        _latest_candle_timestamp(candles),
                        mark_price_timeframe=timeframe,
                    )
                    stack_candles = _load_replay_stack_candles(
                        db,
                        symbol,
                        timeframe,
                        candles,
                        limit,
                        as_of_timestamp=normalized_as_of,
                    )
                stack_resolver = _build_in_memory_stack_resolver(
                    symbol,
                    stack_candles,
                    derivative_history=derivative_history,
                    feature_timeframe=timeframe,
                    regime_detector=regime_detector,
                    transition_policy=transition_policy,
                    risk_min_confidence=risk_min_confidence,
                    risk_confidence_scope=risk_confidence_scope,
                )
                feature_resolver = getattr(stack_resolver, "feature_resolver", None)
                if feature_resolver is None:
                    feature_resolver = _build_in_memory_feature_resolver(
                        symbol,
                        timeframe,
                        candles,
                    )
                context = {
                    "candles": candles,
                    "stack_candles": stack_candles,
                    "derivative_history": derivative_history,
                    "stack_resolver": stack_resolver,
                    "feature_resolver": feature_resolver,
                }
                if replay_context is not None:
                    replay_context["_runtime"] = context
                if normalized_as_of is not None:
                    _FROZEN_REPLAY_CONTEXT_CACHE[context_key] = context
                    while len(_FROZEN_REPLAY_CONTEXT_CACHE) > _FROZEN_REPLAY_CONTEXT_CACHE_MAX:
                        _FROZEN_REPLAY_CONTEXT_CACHE.pop(
                            next(iter(_FROZEN_REPLAY_CONTEXT_CACHE))
                        )
            else:
                candles = context["candles"]
            derivative_history = context["derivative_history"]
            stack_resolver = context["stack_resolver"]
            feature_resolver = context["feature_resolver"]
            replay_decision_cache = {}

            def backtest_runner(items, side, **options):
                return run_filtered_replay(
                    items,
                    side,
                    feature_resolver=feature_resolver,
                    stack_resolver=stack_resolver,
                    initial_capital=options["initial_capital"],
                    position_size_percent=options["position_size_percent"],
                    min_confidence=effective_min_confidence,
                    stop_atr_multiple=options["stop_percent"],
                    target_atr_multiple=options["target_percent"],
                    cooldown_candles=cooldown_candles,
                    fee_bps=options["fee_bps"],
                    slippage_bps=options["slippage_bps"],
                    gate_profile=gate_profile,
                    regime_detector=regime_detector,
                    risk_percent_per_trade=risk_percent_per_trade,
                    target_trade_volatility_percent=target_trade_volatility_percent,
                    max_leverage=max_leverage,
                    max_open_positions=max_open_positions,
                    max_gross_exposure_percent=max_gross_exposure_percent,
                    initial_portfolio_positions=initial_portfolio_positions,
                    collision_policy=collision_policy,
                    profit_protection_mode=profit_protection_mode,
                    profit_protection_activation_r=1.0,
                    timeframe_minutes=TIMEFRAME_MINUTES.get(timeframe, 60),
                    mark_price_records=derivative_history.get("mark_prices"),
                    decision_cache=replay_decision_cache,
                )

            strategy_name = (
                f"RESEARCH_{research_label}_V1"
                if detector_research and research_label
                else
                {
                    "SIGNAL_GATED": "CANDLE_RECONSTRUCTED_REGIME_FILTER_V1",
                    "RESEARCH_CALIBRATION": "CANDLE_RECONSTRUCTED_RESEARCH_GATE_V1",
                    "SHORT_EDGE_CALIBRATION": "CANDLE_RECONSTRUCTED_SHORT_EDGE_RESEARCH_V1",
                    "BEAR_RALLY_EXHAUSTION": (
                        "CANDLE_RECONSTRUCTED_BEAR_RALLY_EXHAUSTION_RESEARCH_V1"
                    ),
                    "PROFIT_PROTECTION_RESEARCH": (
                        "CANDLE_RECONSTRUCTED_PROFIT_PROTECTION_RESEARCH_V1"
                    ),
                }[strategy_key]
            )
            strategy_metadata = {
                "mode": research_label if detector_research and research_label else strategy_key,
                "feature_source": "IN_MEMORY_POINT_IN_TIME_CANDLE_RECONSTRUCTION",
                "timeframe_stack": list(OFFICIAL_ENTRY_TIMEFRAMES),
                "timeframe_stack_source": "IN_MEMORY_POINT_IN_TIME_FINAL_CANDLES",
                "min_confidence": float(effective_min_confidence),
                "cooldown_candles": int(cooldown_candles),
                "gate_profile": gate_profile,
                "regime_detector": regime_detector_key,
                "transition_policy": transition_policy_key,
                "risk_min_confidence": (
                    65.0
                    if risk_min_confidence is None
                    else float(risk_min_confidence)
                ),
                "risk_confidence_scope": risk_confidence_scope_key,
                "production_eligible": not is_research,
                "decision_chain_policy": (
                    "ENFORCED"
                    if not is_research
                    else "BYPASSED_FOR_HISTORICAL_COVERAGE_ONLY"
                ),
                "stop_parameter_model": "ATR_MULTIPLE",
                "target_parameter_model": "ATR_MULTIPLE",
                "sizing_mode": (
                    "FIXED_RISK_CAPPED"
                    if risk_percent_per_trade is not None
                    else "VOLATILITY_TARGETED_CAPPED"
                    if target_trade_volatility_percent is not None
                    else "CAPITAL_PERCENT"
                ),
                "risk_percent_per_trade": risk_percent_per_trade,
                "target_trade_volatility_percent": target_trade_volatility_percent,
                "max_leverage": float(max_leverage),
                "max_open_positions": int(max_open_positions),
                "max_gross_exposure_percent": float(max_gross_exposure_percent),
                "initial_portfolio_positions": list(
                    initial_portfolio_positions or ()
                ),
                "collision_policy": collision_policy,
                "profit_protection_mode": profit_protection_mode,
                "profit_protection_activation_r": 1.0,
                "as_of_timestamp": (
                    normalized_as_of.isoformat()
                    if normalized_as_of is not None
                    else None
                ),
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
            frozen_fold_parameters=frozen_fold_parameters,
        )
        result.update({"symbol": symbol, "timeframe": timeframe})
        return result
    finally:
        if db is not None:
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


def _frozen_replay_context_key(symbol, timeframe, limit, as_of_timestamp):
    normalized = normalize_timestamp_to_utc(as_of_timestamp)
    return (
        str(symbol).upper(),
        str(timeframe),
        int(limit),
        normalized.isoformat() if normalized is not None else None,
    )


def _load_replay_stack_candles(
    db,
    symbol,
    selected_timeframe,
    selected_candles,
    limit,
    *,
    as_of_timestamp=None,
):
    stack = {}
    for timeframe in OFFICIAL_ENTRY_TIMEFRAMES:
        timeframe_limit = _stack_history_limit(
            selected_timeframe,
            timeframe,
            limit,
        )
        stack[timeframe] = (
            selected_candles
            if timeframe == selected_timeframe
            else (
                get_candles_as_of(
                    db,
                    symbol,
                    timeframe,
                    as_of_timestamp,
                    timeframe_limit,
                )
                if as_of_timestamp is not None
                else get_latest_candles(
                    db,
                    symbol,
                    timeframe,
                    timeframe_limit,
                )
            )
        )
    return stack


def _stack_history_limit(selected_timeframe, target_timeframe, selected_limit):
    selected_minutes = TIMEFRAME_MINUTES.get(str(selected_timeframe), 60)
    target_minutes = TIMEFRAME_MINUTES.get(str(target_timeframe), 60)
    coverage = ceil(
        int(selected_limit) * selected_minutes / target_minutes
    )
    return max(50, coverage + 300)


def _build_in_memory_stack_resolver(
    symbol,
    candles_by_timeframe,
    derivative_history=None,
    feature_timeframe=None,
    stateful_timelines=None,
    stack_cache=None,
    regime_detector=None,
    transition_policy=None,
    risk_min_confidence=None,
    risk_confidence_scope=None,
):
    cache = stack_cache if stack_cache is not None else {}
    decision_timeframe = str(feature_timeframe or "1h")
    regime_detector_key = getattr(
        regime_detector,
        "__name__",
        "detect_regime",
    )
    transition_policy_key = getattr(
        transition_policy,
        "__name__",
        "production_hysteresis",
    )
    risk_min_confidence_key = (
        "production_40"
        if risk_min_confidence is None
        else f"research_{float(risk_min_confidence):g}"
    )
    risk_confidence_scope_key = str(
        risk_confidence_scope or "PRODUCTION_ALL"
    ).upper()
    bounded_history_resolver = _build_bounded_stack_history_resolver(
        candles_by_timeframe,
    )
    stateful_timelines = stateful_timelines or {
        timeframe: build_stateful_intelligence_timeline(
            symbol,
            timeframe,
            candles,
            full_snapshots=timeframe == "1h",
            regime_detector=regime_detector,
            transition_policy=transition_policy,
        )
        for timeframe, candles in (candles_by_timeframe or {}).items()
    }

    def stateful_builder(
        builder_symbol,
        timeframe,
        history,
        *,
        effective_timestamp=None,
        **_timestamps,
    ):
        resolved = resolve_intelligence_timeline(
            stateful_timelines.get(timeframe),
            effective_timestamp,
        )
        if resolved is None or "signal" in resolved:
            return resolved
        return _enrich_state_snapshot(
            builder_symbol,
            timeframe,
            history,
            resolved,
        )

    def resolve(as_of_timestamp):
        normalized_as_of = normalize_timestamp_to_utc(as_of_timestamp)
        if normalized_as_of is None:
            return None
        cache_key = (
            decision_timeframe,
            regime_detector_key,
            transition_policy_key,
            risk_min_confidence_key,
            risk_confidence_scope_key,
            normalized_as_of.isoformat(),
        )
        if cache_key not in cache:
            stack = build_point_in_time_stack(
                symbol,
                bounded_history_resolver(normalized_as_of),
                normalized_as_of,
                intelligence_builder=stateful_builder,
            )
            derivatives = build_derivatives_as_of(
                (derivative_history or {}).get("funding"),
                (derivative_history or {}).get("open_interest"),
                normalized_as_of,
                mark_price_records=(derivative_history or {}).get("mark_prices"),
                margin_bracket_records=(derivative_history or {}).get("margin_brackets"),
            )
            stack["derivatives"] = derivatives
            decision_record = next(
                (
                    item
                    for item in (stack.get("timeframes") or ())
                    if item.get("timeframe") == decision_timeframe
                ),
                None,
            )
            entry_intelligence = (
                decision_record.get("intelligence")
                if decision_record is not None
                else None
            )
            stack["decision_chain"] = build_replay_decision_chain(
                symbol,
                decision_timeframe,
                entry_intelligence,
                derivatives,
                risk_min_confidence=risk_min_confidence,
                risk_confidence_scope=risk_confidence_scope,
            )
            stack["decision_chain_timeframe"] = decision_timeframe
            stack["event_state_scope"] = {
                "derivatives": derivatives["status"],
                "contradiction": "REPLAYED",
                "risk": "REPLAYED",
                "executor": "SIMULATED_NO_SIDE_EFFECTS",
            }
            cache[cache_key] = stack
        return cache[cache_key]

    timeline_key = feature_timeframe or "1h"

    def feature_resolver(as_of_timestamp):
        resolved = resolve_intelligence_timeline(
            stateful_timelines.get(timeline_key),
            as_of_timestamp,
        )
        if resolved is None or "feature" not in resolved:
            return None
        return {
            "symbol": symbol,
            "timeframe": timeline_key,
            "source_timestamp": resolved.get("source_timestamp"),
            "effective_timestamp": resolved.get("effective_timestamp"),
            "feature_version": "feature_factory_v1",
            "quality_state": "RECONSTRUCTED",
            "feature": resolved["feature"],
        }

    resolve.feature_resolver = feature_resolver
    resolve.stateful_timelines = stateful_timelines
    resolve.stack_cache = cache
    resolve.decision_timeframe = decision_timeframe
    resolve.regime_detector_key = regime_detector_key
    resolve.transition_policy_key = transition_policy_key
    resolve.risk_min_confidence_key = risk_min_confidence_key
    resolve.risk_confidence_scope_key = risk_confidence_scope_key
    return resolve


def _enrich_state_snapshot(symbol, timeframe, history, state_snapshot):
    """Add stack fields to a state-only higher-timeframe snapshot cheaply."""
    feature = state_snapshot.get("feature") or {}
    regime = state_snapshot.get("regime") or {}
    orderflow = state_snapshot.get("orderflow") or {}
    smc = analyze_smc(history)
    feature_row = SimpleNamespace(
        Symbol=symbol,
        Timeframe=timeframe,
        Trend=feature.get("trend"),
        TrendScore=feature.get("trend_score"),
        MomentumScore=feature.get("momentum_score"),
        VolatilityScore=feature.get("volatility_score"),
        LiquidityScore=feature.get("liquidity_score"),
        FinalScore=feature.get("final_score"),
        Signal=feature.get("signal"),
    )
    regime_row = SimpleNamespace(
        Regime=regime.get("regime"),
        Confidence=regime.get("confidence"),
    )
    orderflow_row = SimpleNamespace(
        FlowSignal=orderflow.get("signal"),
        Confidence=orderflow.get("confidence"),
        BuyerStrength=orderflow.get("buyer_strength"),
        SellerStrength=orderflow.get("seller_strength"),
        Delta=orderflow.get("delta"),
        CVD=orderflow.get("cvd"),
    )
    smc_row = SimpleNamespace(
        smc_bias=smc.get("bias"),
        confidence=smc.get("confidence"),
        structure=(smc.get("bos") or {}).get("direction"),
    )
    current_price = _candle_numeric_value(history[-1], "close_price") if history else None
    previous_price = (
        _candle_numeric_value(history[-2], "close_price")
        if len(history) > 1
        else None
    )
    price_change_pct = (
        ((current_price - previous_price) / previous_price) * 100
        if current_price is not None and previous_price not in (None, 0)
        else None
    )
    return {
        **state_snapshot,
        "smc": smc,
        "signal": generate_master_signal(
            feature_row,
            regime_row,
            orderflow_row,
            smc_row,
        ),
        "current_price": current_price,
        "previous_price": previous_price,
        "price_change_pct": (
            round(price_change_pct, 6) if price_change_pct is not None else None
        ),
        "availability": {
            **(state_snapshot.get("availability") or {}),
            "smc": "RECONSTRUCTED",
            "derivatives": "NOT_SUPPLIED",
            "contradiction": "NOT_SUPPLIED",
            "risk": "NOT_SUPPLIED",
            "executor": "NOT_SUPPLIED",
        },
        "leakage_status": "PASS",
    }


def _candle_numeric_value(candle, name):
    value = candle.get(name) if isinstance(candle, dict) else getattr(candle, name, None)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _build_bounded_stack_history_resolver(candles_by_timeframe, history_limit=300):
    """Index final candle close times so each replay cutoff scans bounded history."""

    indexed = {}
    for timeframe, candles in (candles_by_timeframe or {}).items():
        eligible = []
        for candle in candles or []:
            is_final = (
                candle.get("is_final", True)
                if isinstance(candle, dict)
                else getattr(candle, "is_final", True)
            )
            if is_final is False:
                continue
            candle_time = (
                candle.get("candle_time") or candle.get("open_time")
                if isinstance(candle, dict)
                else (
                    getattr(candle, "candle_time", None)
                    or getattr(candle, "open_time", None)
                )
            )
            close_time = (
                candle.get("close_time") or candle_time
                if isinstance(candle, dict)
                else getattr(candle, "close_time", None) or candle_time
            )
            normalized_candle_time = normalize_timestamp_to_utc(candle_time)
            normalized_close_time = normalize_timestamp_to_utc(close_time)
            if normalized_candle_time is None or normalized_close_time is None:
                continue
            eligible.append(
                (normalized_candle_time, normalized_close_time, candle)
            )
        eligible.sort(key=lambda item: item[0])
        indexed[timeframe] = (
            [item[1] for item in eligible],
            [item[2] for item in eligible],
        )

    def resolve(as_of_timestamp):
        cutoff = normalize_timestamp_to_utc(as_of_timestamp)
        bounded = {}
        for timeframe, (close_times, candles) in indexed.items():
            end = bisect_right(close_times, cutoff)
            bounded[timeframe] = candles[
                max(0, end - int(history_limit)):end
            ]
        return bounded

    return resolve


def _latest_candle_timestamp(candles):
    if not candles:
        return None
    latest = candles[-1]
    return (
        getattr(latest, "close_time", None)
        or getattr(latest, "candle_time", None)
    )
