from collections import Counter
from dataclasses import asdict
from dataclasses import dataclass
from itertools import product
from math import sqrt
from statistics import mean
from statistics import pstdev

from app.backtesting.backtest_engine import ENGINE_VERSION
from app.backtesting.backtest_engine import chronological_candles
from app.backtesting.backtest_engine import run_backtest
from app.backtesting.performance_engine import calculate_performance
from app.backtesting.replay_contract import build_replay_input_contract
from app.trading.futures_cost_model import DEFAULT_FEE_BPS


WALK_FORWARD_VERSION = "walk_forward_v1"
PHASE2_VALIDATION_CONTRACT_VERSION = "phase2_proof_of_edge_v1"
PHASE2_WALK_FORWARD_DAYS = {
    "train_window_days": 180,
    "test_window_days": 60,
    "step_days": 60,
    "minimum_folds": 6,
}
PHASE2_OFFICIAL_TIMEFRAMES = {"1h", "2h", "4h", "1d"}
PHASE2_SUPPORTING_TIMEFRAMES = {"5m", "15m"}
MIN_ANNUALIZED_SHARPE_TRADES = 30
TIMEFRAME_MINUTES = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "1h": 60,
    "2h": 120,
    "4h": 240,
    "1d": 1440,
}


def is_phase2_official_timeframe(timeframe):
    return str(timeframe or "").strip() in PHASE2_OFFICIAL_TIMEFRAMES


@dataclass(frozen=True)
class WalkForwardConfig:
    train_size: int = 200
    test_size: int = 50
    step_size: int = 50
    mode: str = "EXPANDING"
    min_train_trades: int = 3

    def __post_init__(self):
        normalized_mode = str(self.mode).upper()
        if normalized_mode not in {"EXPANDING", "ROLLING"}:
            raise ValueError("mode must be EXPANDING or ROLLING")
        object.__setattr__(self, "mode", normalized_mode)
        if self.train_size < 2:
            raise ValueError("train_size must be at least 2")
        if self.test_size < 1:
            raise ValueError("test_size must be at least 1")
        if self.step_size < self.test_size:
            raise ValueError("step_size must be at least test_size to prevent overlapping test folds")
        if self.min_train_trades < 1:
            raise ValueError("min_train_trades must be at least 1")


def run_walk_forward(
    candles,
    signal,
    *,
    timeframe=None,
    stop_grid=(0.75, 1.0, 1.25, 1.5),
    target_grid=(1.5, 2.0, 2.5, 3.0),
    train_size=200,
    test_size=50,
    step_size=None,
    mode="EXPANDING",
    min_train_trades=3,
    initial_capital=10_000,
    position_size_percent=100,
    fee_bps=DEFAULT_FEE_BPS,
    slippage_bps=2,
    backtest_runner=run_backtest,
    strategy_name="DIRECTIONAL_REENTRY_BASELINE",
    strategy_metadata=None,
    frozen_fold_parameters=None,
):
    side = str(signal or "").upper()
    if side not in {"LONG", "SHORT"}:
        raise ValueError("signal must be LONG or SHORT")

    config = WalkForwardConfig(
        train_size=int(train_size),
        test_size=int(test_size),
        step_size=int(step_size if step_size is not None else test_size),
        mode=mode,
        min_train_trades=int(min_train_trades),
    )
    candidates = _parameter_grid(stop_grid, target_grid)
    ordered = chronological_candles(candles)
    minimum_candles = config.train_size + config.test_size
    if len(ordered) < minimum_candles:
        return _insufficient_data_result(
            side,
            config,
            candidates,
            len(ordered),
            minimum_candles,
            initial_capital,
            timeframe=timeframe,
            strategy_name=strategy_name,
            strategy_metadata=strategy_metadata,
        )

    folds = []
    all_oos_trades = []
    aggregate_equity = [
        {
            "label": _candle_time(ordered[0]),
            "equity": round(float(initial_capital), 2),
        }
    ]
    oos_capital = float(initial_capital)
    total_test_candles = 0
    weighted_exposure = 0
    gate_evaluated = 0
    gate_signal_counts = Counter()
    gate_rejection_counts = Counter()
    gate_regime_counts = Counter()
    gate_regime_direction_counts = Counter()
    gate_regime_source_counts = Counter()
    gate_pass_counts = Counter()
    gate_rejection_combination_counts = Counter()
    gate_score_distributions = {}
    gate_master_signal_diagnostics = {}
    gate_directional_entry_funnel = {
        "evaluated": 0,
        "candidate_regimes": Counter(),
        "cumulative_stage_counts": Counter(),
        "independent_condition_pass_counts": Counter(),
        "first_failure_counts": Counter(),
        "confirmed_candidate_score_distributions": {},
        "master_candidate_chain_audit": {
            "evaluated": 0,
            "contradiction_statuses": Counter(),
            "contradiction_trade_allowed": Counter(),
            "conflict_scores": {},
            "master_signal_scores": {},
            "master_signal_confidences": {},
            "risk_confidences": {},
            "conflict_names": Counter(),
            "conflict_severities": Counter(),
            "bias_maps": {},
            "risk_decisions": Counter(),
            "risk_reasons": Counter(),
            "executor_verdicts": Counter(),
            "current_price_availability": Counter(),
        },
        "contract": {},
    }
    test_start = config.train_size
    frozen_selections = list(frozen_fold_parameters or [])

    while test_start + config.test_size <= len(ordered):
        train_start = 0 if config.mode == "EXPANDING" else test_start - config.train_size
        train_end = test_start
        test_end = test_start + config.test_size
        train_candles = ordered[train_start:train_end]
        test_candles = ordered[test_start:test_end]

        fold_number = len(folds) + 1
        if frozen_selections:
            selected, leaderboard = _evaluate_frozen_selection(
                train_candles,
                side,
                candidates,
                frozen_selections,
                fold_number,
                config,
                initial_capital,
                position_size_percent,
                fee_bps,
                slippage_bps,
                backtest_runner,
            )
        else:
            selected, leaderboard = _select_parameters(
                train_candles,
                side,
                candidates,
                config,
                initial_capital,
                position_size_percent,
                fee_bps,
                slippage_bps,
                backtest_runner,
            )
        # The last training candle supplies only the decision context needed to
        # enter at the first test candle's open. No test candle participates in
        # parameter selection.
        oos_input = [train_candles[-1], *test_candles]
        oos_result = backtest_runner(
            oos_input,
            side,
            stop_percent=selected["stop_percent"],
            target_percent=selected["target_percent"],
            initial_capital=oos_capital,
            position_size_percent=position_size_percent,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
        )
        decision_summary = oos_result.get("decision_summary") or {}
        gate_evaluated += int(decision_summary.get("evaluated") or 0)
        gate_signal_counts.update(decision_summary.get("signals") or {})
        gate_rejection_counts.update(decision_summary.get("rejections") or {})
        gate_regime_counts.update(decision_summary.get("regimes") or {})
        gate_regime_direction_counts.update(
            decision_summary.get("regime_directions") or {}
        )
        gate_regime_source_counts.update(decision_summary.get("regime_sources") or {})
        gate_pass_counts.update(
            decision_summary.get("independent_gate_pass_counts") or {}
        )
        gate_rejection_combination_counts.update(
            decision_summary.get("rejection_combinations") or {}
        )
        _merge_score_distributions(
            gate_score_distributions,
            decision_summary.get("feature_score_distributions") or {},
        )
        _merge_master_signal_diagnostics(
            gate_master_signal_diagnostics,
            decision_summary.get("master_signal_diagnostics") or {},
        )
        _merge_directional_entry_funnel(
            gate_directional_entry_funnel,
            decision_summary.get("directional_entry_funnel") or {},
        )
        fold_trades = [
            {**trade, "fold": fold_number}
            for trade in oos_result.get("trades", [])
        ]
        all_oos_trades.extend(fold_trades)
        aggregate_equity.extend(oos_result.get("equity_curve", [])[1:])
        oos_capital = float(oos_result.get("final_capital", oos_capital))
        total_test_candles += len(test_candles)
        weighted_exposure += float(oos_result.get("exposure_percent", 0)) * len(test_candles)

        folds.append(
            {
                "fold": fold_number,
                "train": {
                    "start": _candle_time(train_candles[0]),
                    "end": _candle_time(train_candles[-1]),
                    "candle_count": len(train_candles),
                },
                "test": {
                    "start": _candle_time(test_candles[0]),
                    "end": _candle_time(test_candles[-1]),
                    "candle_count": len(test_candles),
                },
                "selected_parameters": {
                    "stop_percent": selected["stop_percent"],
                    "target_percent": selected["target_percent"],
                },
                "selection": {
                    "status": selected["status"],
                    "score": selected["score"],
                    "train_trades": selected["total_trades"],
                    "train_return_percent": selected["total_return_percent"],
                    "train_max_drawdown_percent": selected["max_drawdown_percent"],
                    "top_candidates": leaderboard[:3],
                },
                "out_of_sample": _compact_result(oos_result),
            }
        )
        test_start += config.step_size

    aggregate = calculate_performance(
        all_oos_trades,
        initial_capital=float(initial_capital),
        final_capital=oos_capital,
        equity_curve=aggregate_equity,
    )
    profitable_folds = sum(
        1 for fold in folds if fold["out_of_sample"]["total_return_percent"] > 0
    )
    selection_counts = Counter(
        (
            fold["selected_parameters"]["stop_percent"],
            fold["selected_parameters"]["target_percent"],
        )
        for fold in folds
    )
    insufficient_folds = sum(
        fold["selection"]["status"] not in {"SELECTED", "FROZEN"}
        for fold in folds
    )

    return {
        "engine_version": WALK_FORWARD_VERSION,
        "backtest_engine_version": ENGINE_VERSION,
        "validation_status": "VALID" if not insufficient_folds else "LIMITED_TRAINING_TRADES",
        "strategy": strategy_name,
        "strategy_metadata": dict(strategy_metadata or {}),
        "signal": side,
        "candle_count": len(ordered),
        "fold_count": len(folds),
        "folds": folds,
        "out_of_sample": {
            **aggregate,
            "total_trades": len(all_oos_trades),
            "trades": all_oos_trades,
            "equity_curve": aggregate_equity,
            "exposure_percent": round(
                weighted_exposure / total_test_candles if total_test_candles else 0,
                2,
            ),
            "gate_diagnostics": {
                "evaluated_decisions": gate_evaluated,
                "signals": dict(sorted(gate_signal_counts.items())),
                "rejections": dict(sorted(gate_rejection_counts.items())),
                "regimes": dict(sorted(gate_regime_counts.items())),
                "regime_percentages": _percentage_distribution(
                    gate_regime_counts,
                    gate_evaluated,
                ),
                "regime_directions": dict(
                    sorted(gate_regime_direction_counts.items())
                ),
                "regime_sources": dict(sorted(gate_regime_source_counts.items())),
                "regime_direction_percentages": _percentage_distribution(
                    gate_regime_direction_counts,
                    gate_evaluated,
                ),
                "independent_gate_pass_counts": dict(sorted(gate_pass_counts.items())),
                "independent_gate_pass_percentages": _percentage_distribution(
                    gate_pass_counts,
                    gate_evaluated,
                ),
                "rejection_combinations": dict(
                    gate_rejection_combination_counts.most_common()
                ),
                "feature_score_distributions": _serialize_score_distributions(
                    gate_score_distributions
                ),
                "master_signal_diagnostics": _serialize_master_signal_diagnostics(
                    gate_master_signal_diagnostics
                ),
                "directional_entry_funnel": _serialize_directional_entry_funnel(
                    gate_directional_entry_funnel
                ),
            },
            "annualized_sharpe": _annualized_trade_horizon_sharpe(
                all_oos_trades,
                timeframe,
            ),
            "annualized_sharpe_method": "TRADE_RETURN_SHARPE_ANNUALIZED_BY_AVERAGE_CANDLE_HOLD",
            "annualized_sharpe_min_trade_sample": MIN_ANNUALIZED_SHARPE_TRADES,
        },
        "robustness": {
            "profitable_folds": profitable_folds,
            "losing_folds": len(folds) - profitable_folds,
            "profitable_fold_percent": round(
                (profitable_folds / len(folds)) * 100 if folds else 0,
                2,
            ),
            "insufficient_training_trade_folds": insufficient_folds,
            "parameter_selection_counts": [
                {
                    "stop_percent": key[0],
                    "target_percent": key[1],
                    "folds": count,
                }
                for key, count in sorted(selection_counts.items())
            ],
        },
        "configuration": {
            **asdict(config),
            "stop_grid": sorted(set(item["stop_percent"] for item in candidates)),
            "target_grid": sorted(set(item["target_percent"] for item in candidates)),
            "initial_capital": float(initial_capital),
            "position_size_percent": float(position_size_percent),
            "fee_bps": float(fee_bps),
            "slippage_bps": float(slippage_bps),
            "selection_mode": (
                "FROZEN_FOLD_PARAMETERS"
                if frozen_selections
                else "TRAINING_GRID_SELECTION"
            ),
            "frozen_fold_parameters": frozen_selections,
        },
        "validation_contract": _phase2_validation_contract_summary(
            timeframe,
            config,
            len(folds),
            len(ordered),
        ),
        "replay_contract": build_replay_input_contract(timeframe),
        "leakage_controls": {
            "parameter_selection": "TRAIN_ONLY",
            "test_policy": "FROZEN_PARAMETERS",
            "test_overlap": "DISALLOWED",
            "first_test_entry": "FIRST_TEST_CANDLE_OPEN_USING_LAST_TRAIN_CANDLE_CONTEXT",
            "fold_boundary_position": "CLOSE_AT_TEST_WINDOW_END",
        },
    }


def _parameter_grid(stop_grid, target_grid):
    stops = sorted(set(_positive_values(stop_grid, "stop_grid")))
    targets = sorted(set(_positive_values(target_grid, "target_grid")))
    return [
        {"stop_percent": stop, "target_percent": target}
        for stop, target in product(stops, targets)
    ]


def _positive_values(values, name):
    parsed = [float(value) for value in values]
    if not parsed or any(value <= 0 for value in parsed):
        raise ValueError(f"{name} must contain positive values")
    return parsed


def _select_parameters(
    train_candles,
    side,
    candidates,
    config,
    initial_capital,
    position_size_percent,
    fee_bps,
    slippage_bps,
    backtest_runner,
):
    scored = []
    for candidate in candidates:
        result = backtest_runner(
            train_candles,
            side,
            stop_percent=candidate["stop_percent"],
            target_percent=candidate["target_percent"],
            initial_capital=initial_capital,
            position_size_percent=position_size_percent,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
        )
        total_trades = int(result.get("total_trades", 0))
        train_return = float(result.get("total_return_percent", 0))
        drawdown = float(result.get("max_drawdown_percent", 0))
        score = train_return - drawdown
        eligible = total_trades >= config.min_train_trades
        scored.append(
            {
                **candidate,
                "eligible": eligible,
                "status": "SELECTED" if eligible else "INSUFFICIENT_TRAIN_TRADES",
                "score": round(score, 4),
                "total_trades": total_trades,
                "total_return_percent": round(train_return, 4),
                "max_drawdown_percent": round(drawdown, 4),
                "sharpe_ratio": float(result.get("sharpe_ratio", 0)),
            }
        )

    eligible = [item for item in scored if item["eligible"]]
    pool = eligible or scored
    if eligible:
        rank_key = lambda item: (
            item["score"],
            item["sharpe_ratio"],
            item["total_trades"],
            -item["stop_percent"],
            -item["target_percent"],
        )
    else:
        rank_key = lambda item: (
            item["total_trades"],
            item["score"],
            item["sharpe_ratio"],
            -item["stop_percent"],
            -item["target_percent"],
        )
    ranked = sorted(pool, key=rank_key, reverse=True)
    selected = {**ranked[0]}
    if not eligible:
        selected["status"] = "INSUFFICIENT_TRAIN_TRADES"
    leaderboard = [
        {
            "stop_percent": item["stop_percent"],
            "target_percent": item["target_percent"],
            "score": item["score"],
            "total_trades": item["total_trades"],
            "eligible": item["eligible"],
        }
        for item in ranked
    ]
    return selected, leaderboard


def _evaluate_frozen_selection(
    train_candles,
    side,
    candidates,
    frozen_selections,
    fold_number,
    config,
    initial_capital,
    position_size_percent,
    fee_bps,
    slippage_bps,
    backtest_runner,
):
    if fold_number > len(frozen_selections):
        raise ValueError("frozen fold parameters do not cover every replay fold")
    raw_selection = dict(frozen_selections[fold_number - 1])
    selection = {
        "stop_percent": float(raw_selection["stop_percent"]),
        "target_percent": float(raw_selection["target_percent"]),
    }
    if selection not in candidates:
        raise ValueError("frozen fold parameters must belong to the declared parameter grid")
    result = backtest_runner(
        train_candles,
        side,
        stop_percent=selection["stop_percent"],
        target_percent=selection["target_percent"],
        initial_capital=initial_capital,
        position_size_percent=position_size_percent,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
    )
    total_trades = int(result.get("total_trades", 0))
    train_return = float(result.get("total_return_percent", 0))
    drawdown = float(result.get("max_drawdown_percent", 0))
    selected = {
        **selection,
        "eligible": total_trades >= config.min_train_trades,
        "status": "FROZEN",
        "score": round(train_return - drawdown, 4),
        "total_trades": total_trades,
        "total_return_percent": round(train_return, 4),
        "max_drawdown_percent": round(drawdown, 4),
        "sharpe_ratio": float(result.get("sharpe_ratio", 0)),
    }
    return selected, [
        {
            "stop_percent": selection["stop_percent"],
            "target_percent": selection["target_percent"],
            "score": selected["score"],
            "total_trades": total_trades,
            "eligible": selected["eligible"],
        }
    ]


def _compact_result(result):
    keys = (
        "total_trades",
        "wins",
        "losses",
        "win_rate",
        "profit_factor",
        "total_return_percent",
        "max_drawdown_percent",
        "expectancy_percent",
        "sharpe_ratio",
        "fees_paid",
        "initial_capital",
        "final_capital",
        "exposure_percent",
        "decision_summary",
        "annualized_sharpe",
        "annualized_sharpe_method",
    )
    compact = {key: result.get(key) for key in keys}
    if compact.get("decision_summary") is None:
        compact.pop("decision_summary", None)
    return compact


def _annualized_trade_horizon_sharpe(trades, timeframe):
    """Annualize trade returns using the average candle holding period.

    This is a trade-horizon estimate, not a replacement for a full
    mark-to-market daily Sharpe series.
    """
    returns = []
    durations = []
    for trade in list(trades or []):
        try:
            value = float(trade.get("pnl_percent"))
            duration = float(trade.get("duration_candles"))
        except (TypeError, ValueError):
            continue
        if duration <= 0:
            continue
        returns.append(value)
        durations.append(duration)

    if len(returns) < MIN_ANNUALIZED_SHARPE_TRADES or not durations:
        return None
    deviation = pstdev(returns)
    if deviation == 0:
        return 0.0
    minutes = TIMEFRAME_MINUTES.get(str(timeframe or "").lower())
    if not minutes:
        return None
    periods_per_year = (365 * 24 * 60) / minutes
    trades_per_year = periods_per_year / max(mean(durations), 1.0)
    return round((mean(returns) / deviation) * sqrt(trades_per_year), 4)


def _percentage_distribution(counts, total):
    if not total:
        return {}
    return {
        key: round((value / total) * 100, 2)
        for key, value in sorted(counts.items())
    }


def _merge_score_distributions(target, incoming):
    for name, distribution in incoming.items():
        aggregate = target.setdefault(
            name,
            {
                "count": 0,
                "value_sum": 0.0,
                "minimum": None,
                "maximum": None,
                "buckets": Counter(),
            },
        )
        count = int(distribution.get("count") or 0)
        aggregate["count"] += count
        aggregate["value_sum"] += float(distribution.get("value_sum") or 0)
        minimum = distribution.get("minimum")
        maximum = distribution.get("maximum")
        if minimum is not None:
            aggregate["minimum"] = (
                float(minimum)
                if aggregate["minimum"] is None
                else min(aggregate["minimum"], float(minimum))
            )
        if maximum is not None:
            aggregate["maximum"] = (
                float(maximum)
                if aggregate["maximum"] is None
                else max(aggregate["maximum"], float(maximum))
            )
        aggregate["buckets"].update(distribution.get("buckets") or {})


def _serialize_score_distributions(distributions):
    result = {}
    for name, distribution in sorted(distributions.items()):
        count = distribution["count"]
        result[name] = {
            "count": count,
            "minimum": distribution["minimum"],
            "maximum": distribution["maximum"],
            "average": (
                round(distribution["value_sum"] / count, 4) if count else None
            ),
            "value_sum": round(distribution["value_sum"], 6),
            "buckets": dict(sorted(distribution["buckets"].items())),
        }
    return result


def _merge_master_signal_diagnostics(target, incoming):
    for scope, diagnostics in incoming.items():
        aggregate = target.setdefault(
            scope,
            {
                "evaluated": 0,
                "signals": Counter(),
                "biases": Counter(),
                "scores": {},
                "components": {},
            },
        )
        aggregate["evaluated"] += int(diagnostics.get("evaluated") or 0)
        aggregate["signals"].update(diagnostics.get("signals") or {})
        aggregate["biases"].update(diagnostics.get("biases") or {})
        _merge_score_distributions(
            aggregate["scores"],
            {"master": diagnostics.get("score_distribution") or {}},
        )
        for name, component in (diagnostics.get("components") or {}).items():
            component_aggregate = aggregate["components"].setdefault(
                name,
                {"values": Counter(), "scores": {}},
            )
            component_aggregate["values"].update(component.get("values") or {})
            _merge_score_distributions(
                component_aggregate["scores"],
                {"component": component.get("score_distribution") or {}},
            )


def _serialize_master_signal_diagnostics(diagnostics):
    result = {}
    for scope, aggregate in sorted(diagnostics.items()):
        scores = _serialize_score_distributions(aggregate["scores"])
        result[scope] = {
            "evaluated": aggregate["evaluated"],
            "signals": dict(sorted(aggregate["signals"].items())),
            "biases": dict(sorted(aggregate["biases"].items())),
            "score_distribution": scores.get("master", {}),
            "components": {},
        }
        for name, component in sorted(aggregate["components"].items()):
            component_scores = _serialize_score_distributions(component["scores"])
            result[scope]["components"][name] = {
                "values": dict(sorted(component["values"].items())),
                "score_distribution": component_scores.get("component", {}),
            }
    return result


def _merge_directional_entry_funnel(target, incoming):
    target["evaluated"] += int(incoming.get("evaluated") or 0)
    target["candidate_regimes"].update(incoming.get("candidate_regimes") or {})
    target["cumulative_stage_counts"].update(
        incoming.get("cumulative_stage_counts") or {}
    )
    target["independent_condition_pass_counts"].update(
        incoming.get("independent_condition_pass_counts") or {}
    )
    target["first_failure_counts"].update(incoming.get("first_failure_counts") or {})
    _merge_score_distributions(
        target["confirmed_candidate_score_distributions"],
        incoming.get("confirmed_candidate_score_distributions") or {},
    )
    _merge_master_candidate_chain_audit(
        target["master_candidate_chain_audit"],
        incoming.get("master_candidate_chain_audit") or {},
    )
    contract = incoming.get("contract") or {}
    if contract:
        target["contract"] = contract


def _serialize_directional_entry_funnel(diagnostics):
    stage_order = list((diagnostics.get("contract") or {}).get("stage_order") or ())
    cumulative = diagnostics.get("cumulative_stage_counts") or {}
    candidates = int(cumulative.get("SAME_SIDE_CANDIDATE_REGIME", 0))
    final_eligible = int(cumulative.get("FINAL_ELIGIBLE", 0))
    first_failures = diagnostics.get("first_failure_counts") or {}
    return {
        "evaluated": int(diagnostics.get("evaluated") or 0),
        "candidate_regimes": dict(sorted(diagnostics["candidate_regimes"].items())),
        "cumulative_stage_counts": {
            stage: int(cumulative.get(stage, 0)) for stage in stage_order
        },
        "cumulative_stage_percent_of_candidates": {
            stage: round(int(cumulative.get(stage, 0)) / candidates * 100, 2)
            if candidates
            else 0.0
            for stage in stage_order
        },
        "independent_condition_pass_counts": {
            stage: int(
                diagnostics["independent_condition_pass_counts"].get(stage, 0)
            )
            for stage in stage_order
        },
        "first_failure_counts": dict(sorted(first_failures.items())),
        "confirmed_candidate_score_distributions": _serialize_score_distributions(
            diagnostics["confirmed_candidate_score_distributions"]
        ),
        "master_candidate_chain_audit": _serialize_master_candidate_chain_audit(
            diagnostics["master_candidate_chain_audit"]
        ),
        "contract": {
            "scope": "READ_ONLY_DIAGNOSTIC",
            "candidate_denominator": candidates,
            "stage_order": stage_order,
            "first_failures_reconcile_to_candidates": (
                sum(first_failures.values()) + final_eligible == candidates
            ),
        },
    }


def _merge_master_candidate_chain_audit(target, incoming):
    target["evaluated"] += int(incoming.get("evaluated") or 0)
    for name in (
        "contradiction_statuses",
        "contradiction_trade_allowed",
        "conflict_names",
        "conflict_severities",
        "risk_decisions",
        "risk_reasons",
        "executor_verdicts",
        "current_price_availability",
    ):
        target[name].update(incoming.get(name) or {})
    _merge_score_distributions(
        target["conflict_scores"],
        {"conflict_score": incoming.get("conflict_score_distribution") or {}},
    )
    _merge_score_distributions(
        target["master_signal_scores"],
        {"master_signal_score": incoming.get("master_signal_score_distribution") or {}},
    )
    _merge_score_distributions(
        target["master_signal_confidences"],
        {"master_signal_confidence": incoming.get("master_signal_confidence_distribution") or {}},
    )
    _merge_score_distributions(
        target["risk_confidences"],
        {"risk_confidence": incoming.get("risk_confidence_distribution") or {}},
    )
    for source, values in (incoming.get("bias_maps") or {}).items():
        target["bias_maps"].setdefault(source, Counter()).update(values)


def _serialize_master_candidate_chain_audit(diagnostics):
    scores = _serialize_score_distributions(diagnostics["conflict_scores"])
    master_scores = _serialize_score_distributions(diagnostics["master_signal_scores"])
    master_confidences = _serialize_score_distributions(
        diagnostics["master_signal_confidences"]
    )
    risk_confidences = _serialize_score_distributions(diagnostics["risk_confidences"])
    return {
        "evaluated": int(diagnostics.get("evaluated") or 0),
        "contradiction_statuses": dict(sorted(diagnostics["contradiction_statuses"].items())),
        "contradiction_trade_allowed": dict(sorted(diagnostics["contradiction_trade_allowed"].items())),
        "conflict_score_distribution": scores.get("conflict_score", {}),
        "master_signal_score_distribution": master_scores.get("master_signal_score", {}),
        "master_signal_confidence_distribution": master_confidences.get(
            "master_signal_confidence", {}
        ),
        "risk_confidence_distribution": risk_confidences.get("risk_confidence", {}),
        "conflict_names": dict(sorted(diagnostics["conflict_names"].items())),
        "conflict_severities": dict(sorted(diagnostics["conflict_severities"].items())),
        "bias_maps": {
            source: dict(sorted(values.items()))
            for source, values in sorted(diagnostics["bias_maps"].items())
        },
        "risk_decisions": dict(sorted(diagnostics["risk_decisions"].items())),
        "risk_reasons": dict(sorted(diagnostics["risk_reasons"].items())),
        "executor_verdicts": dict(sorted(diagnostics["executor_verdicts"].items())),
        "current_price_availability": dict(sorted(diagnostics["current_price_availability"].items())),
        "scope": "READ_ONLY_MASTER_CANDIDATES_AFTER_TIMEFRAME_GATE",
    }


def _insufficient_data_result(
    side,
    config,
    candidates,
    candle_count,
    required,
    initial_capital,
    timeframe=None,
    strategy_name="DIRECTIONAL_REENTRY_BASELINE",
    strategy_metadata=None,
):
    return {
        "engine_version": WALK_FORWARD_VERSION,
        "backtest_engine_version": ENGINE_VERSION,
        "validation_status": "INSUFFICIENT_DATA",
        "strategy": strategy_name,
        "strategy_metadata": dict(strategy_metadata or {}),
        "signal": side,
        "candle_count": candle_count,
        "required_candle_count": required,
        "fold_count": 0,
        "folds": [],
        "out_of_sample": {
            "total_trades": 0,
            "trades": [],
            "equity_curve": [{"label": "START", "equity": float(initial_capital)}],
        },
        "configuration": {
            **asdict(config),
            "candidate_count": len(candidates),
        },
        "validation_contract": _phase2_validation_contract_summary(
            timeframe,
            config,
            0,
            candle_count,
        ),
        "replay_contract": build_replay_input_contract(timeframe),
    }


def _candle_time(candle):
    value = candle.get("candle_time") if isinstance(candle, dict) else getattr(candle, "candle_time", None)
    return value.isoformat() if hasattr(value, "isoformat") else str(value) if value is not None else None


def phase2_walk_forward_defaults(timeframe):
    timeframe_key = str(timeframe or "").strip()
    minutes = TIMEFRAME_MINUTES.get(timeframe_key)
    if minutes is None:
        raise ValueError(f"Unsupported timeframe for walk-forward contract: {timeframe}")
    candles_per_day = int(1440 / minutes)
    train_size = PHASE2_WALK_FORWARD_DAYS["train_window_days"] * candles_per_day
    test_size = PHASE2_WALK_FORWARD_DAYS["test_window_days"] * candles_per_day
    step_size = PHASE2_WALK_FORWARD_DAYS["step_days"] * candles_per_day
    minimum_fold_candles = minimum_candles_for_folds(
        train_size,
        test_size,
        step_size,
        PHASE2_WALK_FORWARD_DAYS["minimum_folds"],
    )
    return {
        "train_size": train_size,
        "test_size": test_size,
        "step_size": step_size,
        "minimum_fold_candles": minimum_fold_candles,
    }


def minimum_candles_for_folds(train_size, test_size, step_size, minimum_folds):
    additional_folds = max(int(minimum_folds) - 1, 0)
    return int(train_size) + int(test_size) + (int(step_size) * additional_folds)


def _phase2_validation_contract_summary(timeframe, config, fold_count, candle_count):
    timeframe_key = str(timeframe or "").strip()
    timeframe_status = _timeframe_contract_status(timeframe_key)
    defaults = phase2_walk_forward_defaults(timeframe_key) if timeframe_key in TIMEFRAME_MINUTES else None
    issues = []

    if timeframe_status == "NON_CANONICAL":
        issues.append("timeframe_outside_phase2_contract")

    windows_match_contract = bool(
        defaults
        and config.train_size == defaults["train_size"]
        and config.test_size == defaults["test_size"]
        and config.step_size == defaults["step_size"]
    )
    if timeframe_status == "OFFICIAL" and not windows_match_contract:
        issues.append("walk_forward_windows_do_not_match_phase2_contract")

    required_candles = (
        minimum_candles_for_folds(
            config.train_size,
            config.test_size,
            config.step_size,
            PHASE2_WALK_FORWARD_DAYS["minimum_folds"],
        )
        if timeframe_status == "OFFICIAL"
        else None
    )
    if timeframe_status == "OFFICIAL" and fold_count < PHASE2_WALK_FORWARD_DAYS["minimum_folds"]:
        issues.append("minimum_fold_requirement_not_met")

    if timeframe_status == "OFFICIAL" and candle_count < (required_candles or 0):
        issues.append("insufficient_history_for_phase2_fold_requirement")

    if timeframe_status == "OFFICIAL" and windows_match_contract and fold_count >= PHASE2_WALK_FORWARD_DAYS["minimum_folds"]:
        contract_status = "PASS"
    elif timeframe_status == "OFFICIAL":
        contract_status = "INSUFFICIENT_EVIDENCE"
    elif timeframe_status == "SUPPORTING":
        contract_status = "PARTIAL"
    else:
        contract_status = "NOT_APPLICABLE"

    return {
        "contract_version": PHASE2_VALIDATION_CONTRACT_VERSION,
        "timeframe": timeframe_key or None,
        "timeframe_status": timeframe_status,
        "official_timeframes": sorted(PHASE2_OFFICIAL_TIMEFRAMES),
        "supporting_timeframes": sorted(PHASE2_SUPPORTING_TIMEFRAMES),
        "target_windows_days": {**PHASE2_WALK_FORWARD_DAYS},
        "derived_candle_windows": defaults,
        "required_candle_count_for_minimum_folds": required_candles,
        "actual_fold_count": int(fold_count),
        "minimum_fold_requirement": PHASE2_WALK_FORWARD_DAYS["minimum_folds"],
        "contract_status": contract_status,
        "configuration_matches_contract": windows_match_contract if timeframe_status == "OFFICIAL" else None,
        "issues": issues,
    }


def _timeframe_contract_status(timeframe):
    if timeframe in PHASE2_OFFICIAL_TIMEFRAMES:
        return "OFFICIAL"
    if timeframe in PHASE2_SUPPORTING_TIMEFRAMES:
        return "SUPPORTING"
    return "NON_CANONICAL"
