"""Run research-only, one-gate-at-a-time walk-forward ablations.

This runner never persists Phase 2 official artifacts and never changes the
production STRICT profile.  Each worker installs temporary in-process gate
profiles, reuses one frozen point-in-time context per symbol, and writes a
separate diagnostic report.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from app.backtesting import trade_simulator
from app.backtesting.filtered_replay_engine import GATE_PROFILES, run_filtered_replay
from app.backtesting.walk_forward_validator import TIMEFRAME_MINUTES, run_walk_forward
from app.regimes.rules import detect_regime
from app.regimes.rules import detect_regime_momentum_boundary_research
from app.regimes.rules import regime_direction
from app.regimes.regime_engine import direction_aware_transition_research


DEFAULT_SYMBOLS = ("BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT")
DEFAULT_AS_OF = "2026-08-11T11:00:00+00:00"
PROFILE_SPECS = {
    "STRICT_BASELINE": {
        "description": "Unchanged production STRICT gate.",
        "min_confidence": 70,
        "profile": "STRICT",
        "production_eligible": True,
    },
    "DECISION_CHAIN_ABLATION": {
        "description": "Only the historical live decision-chain requirement is disabled.",
        "min_confidence": 70,
        "profile": "ABLATION_NO_DECISION_CHAIN",
        "production_eligible": False,
    },
    "REGIME_REQUIREMENT_ABLATION": {
        "description": "Only strict Bullish/Bearish entry-regime membership is disabled.",
        "min_confidence": 70,
        "profile": "ABLATION_NO_REGIME_REQUIREMENT",
        "production_eligible": False,
    },
    "CONFIDENCE_60_ABLATION": {
        "description": "Only minimum confidence is reduced from 70 to 60.",
        "min_confidence": 60,
        "profile": "STRICT",
        "production_eligible": False,
    },
    "MOMENTUM_BOUNDARY_ALIGNMENT_RESEARCH": {
        "description": (
            "Research-only regime detector changes unreachable trending momentum "
            "boundaries from 62/38 to the feature-reachable 60/40."
        ),
        "min_confidence": 70,
        "profile": "STRICT",
        "regime_detector": "MOMENTUM_BOUNDARY_ALIGNMENT_RESEARCH",
        "production_eligible": False,
    },
    "DIRECTION_AWARE_HYSTERESIS_RESEARCH": {
        "description": (
            "Research-only momentum boundary alignment plus confident opposite-"
            "direction transitions; same-direction and neutral hysteresis remain unchanged."
        ),
        "min_confidence": 70,
        "profile": "STRICT",
        "regime_detector": "MOMENTUM_BOUNDARY_ALIGNMENT_RESEARCH",
        "transition_policy": "DIRECTION_AWARE_HYSTERESIS_RESEARCH",
        "production_eligible": False,
    },
    "DIRECTIONAL_REGIME_EXPANSION_RESEARCH": {
        "description": (
            "Attribution cell A: add Bull pullback/accumulation for LONG and "
            "Bear rally/distribution for SHORT while retaining every strict "
            "feature and decision-chain gate."
        ),
        "min_confidence": 70,
        "profile": "DIRECTIONAL_REGIME_EXPANSION_RESEARCH",
        "research_gate_profile": "DIRECTIONAL_REGIME_EXPANSION_RESEARCH",
        "regime_detector": "MOMENTUM_BOUNDARY_ALIGNMENT_RESEARCH",
        "transition_policy": "DIRECTION_AWARE_HYSTERESIS_RESEARCH",
        "production_eligible": False,
    },
    "DIRECTIONAL_ENTRY_CONFIRMATION_RESEARCH": {
        "description": (
            "Attribution cell B: in added directional pullback/range regimes, "
            "a fully actionable decision chain plus decision-timeframe order-"
            "flow or SMC confirmation substitutes for incompatible feature gates."
        ),
        "min_confidence": 70,
        "profile": "DIRECTIONAL_ENTRY_CONFIRMATION_RESEARCH",
        "research_gate_profile": "DIRECTIONAL_ENTRY_CONFIRMATION_RESEARCH",
        "regime_detector": "MOMENTUM_BOUNDARY_ALIGNMENT_RESEARCH",
        "transition_policy": "DIRECTION_AWARE_HYSTERESIS_RESEARCH",
        "production_eligible": False,
    },
    "DIRECTIONAL_CONFIDENCE_60_RESEARCH": {
        "description": "Directional confirmed-entry profile with only minimum confidence changed to 60.",
        "min_confidence": 60,
        "profile": "DIRECTIONAL_ENTRY_CONFIRMATION_RESEARCH",
        "research_gate_profile": "DIRECTIONAL_ENTRY_CONFIRMATION_RESEARCH",
        "regime_detector": "MOMENTUM_BOUNDARY_ALIGNMENT_RESEARCH",
        "transition_policy": "DIRECTION_AWARE_HYSTERESIS_RESEARCH",
        "production_eligible": False,
    },
    "DIRECTIONAL_CONFIDENCE_62_RESEARCH": {
        "description": "Directional confirmed-entry profile with only minimum confidence changed to 62.",
        "min_confidence": 62,
        "profile": "DIRECTIONAL_ENTRY_CONFIRMATION_RESEARCH",
        "research_gate_profile": "DIRECTIONAL_ENTRY_CONFIRMATION_RESEARCH",
        "regime_detector": "MOMENTUM_BOUNDARY_ALIGNMENT_RESEARCH",
        "transition_policy": "DIRECTION_AWARE_HYSTERESIS_RESEARCH",
        "production_eligible": False,
    },
    "DIRECTIONAL_CONFIDENCE_65_RESEARCH": {
        "description": "Directional confirmed-entry profile with only minimum confidence changed to 65.",
        "min_confidence": 65,
        "profile": "DIRECTIONAL_ENTRY_CONFIRMATION_RESEARCH",
        "research_gate_profile": "DIRECTIONAL_ENTRY_CONFIRMATION_RESEARCH",
        "regime_detector": "MOMENTUM_BOUNDARY_ALIGNMENT_RESEARCH",
        "transition_policy": "DIRECTION_AWARE_HYSTERESIS_RESEARCH",
        "production_eligible": False,
    },
    "DIRECTIONAL_CONFIDENCE_68_RESEARCH": {
        "description": "Directional confirmed-entry profile with only minimum confidence changed to 68.",
        "min_confidence": 68,
        "profile": "DIRECTIONAL_ENTRY_CONFIRMATION_RESEARCH",
        "research_gate_profile": "DIRECTIONAL_ENTRY_CONFIRMATION_RESEARCH",
        "regime_detector": "MOMENTUM_BOUNDARY_ALIGNMENT_RESEARCH",
        "transition_policy": "DIRECTION_AWARE_HYSTERESIS_RESEARCH",
        "production_eligible": False,
    },
    "DIRECTIONAL_RISK_CONFIDENCE_40_RESEARCH": {
        "description": "Directional threshold-60 entry with only risk master-confidence changed to 40.",
        "min_confidence": 60,
        "risk_min_confidence": 40,
        "risk_confidence_scope": "DIRECTIONAL_PULLBACK_RANGE",
        "profile": "DIRECTIONAL_ENTRY_CONFIRMATION_RESEARCH",
        "research_gate_profile": "DIRECTIONAL_ENTRY_CONFIRMATION_RESEARCH",
        "regime_detector": "MOMENTUM_BOUNDARY_ALIGNMENT_RESEARCH",
        "transition_policy": "DIRECTION_AWARE_HYSTERESIS_RESEARCH",
        "production_eligible": False,
    },
    "DIRECTIONAL_RISK_CONFIDENCE_45_RESEARCH": {
        "description": "Directional threshold-60 entry with only risk master-confidence changed to 45.",
        "min_confidence": 60,
        "risk_min_confidence": 45,
        "risk_confidence_scope": "DIRECTIONAL_PULLBACK_RANGE",
        "profile": "DIRECTIONAL_ENTRY_CONFIRMATION_RESEARCH",
        "research_gate_profile": "DIRECTIONAL_ENTRY_CONFIRMATION_RESEARCH",
        "regime_detector": "MOMENTUM_BOUNDARY_ALIGNMENT_RESEARCH",
        "transition_policy": "DIRECTION_AWARE_HYSTERESIS_RESEARCH",
        "production_eligible": False,
    },
    "DIRECTIONAL_RISK_CONFIDENCE_50_RESEARCH": {
        "description": "Directional threshold-60 entry with only risk master-confidence changed to 50.",
        "min_confidence": 60,
        "risk_min_confidence": 50,
        "risk_confidence_scope": "DIRECTIONAL_PULLBACK_RANGE",
        "profile": "DIRECTIONAL_ENTRY_CONFIRMATION_RESEARCH",
        "research_gate_profile": "DIRECTIONAL_ENTRY_CONFIRMATION_RESEARCH",
        "regime_detector": "MOMENTUM_BOUNDARY_ALIGNMENT_RESEARCH",
        "transition_policy": "DIRECTION_AWARE_HYSTERESIS_RESEARCH",
        "production_eligible": False,
    },
    "DIRECTIONAL_RISK_CONFIDENCE_55_RESEARCH": {
        "description": "Directional threshold-60 entry with only risk master-confidence changed to 55.",
        "min_confidence": 60,
        "risk_min_confidence": 55,
        "risk_confidence_scope": "DIRECTIONAL_PULLBACK_RANGE",
        "profile": "DIRECTIONAL_ENTRY_CONFIRMATION_RESEARCH",
        "research_gate_profile": "DIRECTIONAL_ENTRY_CONFIRMATION_RESEARCH",
        "regime_detector": "MOMENTUM_BOUNDARY_ALIGNMENT_RESEARCH",
        "transition_policy": "DIRECTION_AWARE_HYSTERESIS_RESEARCH",
        "production_eligible": False,
    },
    "DIRECTIONAL_RISK_CONFIDENCE_60_RESEARCH": {
        "description": "Directional threshold-60 entry with only risk master-confidence changed to 60.",
        "min_confidence": 60,
        "risk_min_confidence": 60,
        "risk_confidence_scope": "DIRECTIONAL_PULLBACK_RANGE",
        "profile": "DIRECTIONAL_ENTRY_CONFIRMATION_RESEARCH",
        "research_gate_profile": "DIRECTIONAL_ENTRY_CONFIRMATION_RESEARCH",
        "regime_detector": "MOMENTUM_BOUNDARY_ALIGNMENT_RESEARCH",
        "transition_policy": "DIRECTION_AWARE_HYSTERESIS_RESEARCH",
        "production_eligible": False,
    },
    "DIRECTIONAL_RISK_CONFIDENCE_65_RESEARCH": {
        "description": "Directional threshold-60 entry with explicit production-equivalent risk master-confidence 65.",
        "min_confidence": 60,
        "risk_min_confidence": 65,
        "risk_confidence_scope": "DIRECTIONAL_PULLBACK_RANGE",
        "profile": "DIRECTIONAL_ENTRY_CONFIRMATION_RESEARCH",
        "research_gate_profile": "DIRECTIONAL_ENTRY_CONFIRMATION_RESEARCH",
        "regime_detector": "MOMENTUM_BOUNDARY_ALIGNMENT_RESEARCH",
        "transition_policy": "DIRECTION_AWARE_HYSTERESIS_RESEARCH",
        "production_eligible": False,
    },
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--timeframe", default="4h")
    parser.add_argument("--signals", default="LONG,SHORT")
    parser.add_argument("--profiles", default=",".join(PROFILE_SPECS))
    parser.add_argument("--limit", type=int, default=720)
    parser.add_argument("--train-size", type=int, default=360)
    parser.add_argument("--test-size", type=int, default=120)
    parser.add_argument("--step-size", type=int, default=120)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--as-of", default=DEFAULT_AS_OF)
    parser.add_argument("--output-dir", default="outputs/gate_ablation_20260811")
    args = parser.parse_args()

    symbols = _csv(args.symbols)
    signals = _csv(args.signals)
    profiles = _csv(args.profiles)
    if not symbols or any(side not in {"LONG", "SHORT"} for side in signals):
        raise ValueError("symbols are required and signals must be LONG or SHORT")
    unknown_profiles = sorted(set(profiles) - set(PROFILE_SPECS))
    if not profiles or unknown_profiles:
        raise ValueError(f"profiles must be selected from {sorted(PROFILE_SPECS)}")
    as_of = datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
    started = datetime.now(timezone.utc)
    worker_args = [
        {
            "symbol": symbol,
            "timeframe": args.timeframe,
            "signals": signals,
            "profiles": profiles,
            "limit": args.limit,
            "train_size": args.train_size,
            "test_size": args.test_size,
            "step_size": args.step_size,
            "as_of": as_of.isoformat(),
        }
        for symbol in symbols
    ]

    print(
        f"gate ablation starting symbols={len(symbols)} profiles={len(profiles)} "
        f"sides={len(signals)} timeframe={args.timeframe} as_of={as_of.isoformat()}",
        flush=True,
    )
    results = []
    worker_count = max(1, min(args.workers, len(symbols)))
    if worker_count == 1:
        results = [_run_symbol(item) for item in worker_args]
    else:
        with ProcessPoolExecutor(max_workers=worker_count) as executor:
            futures = {executor.submit(_run_symbol, item): item["symbol"] for item in worker_args}
            for future in as_completed(futures):
                symbol = futures[future]
                result = future.result()
                results.append(result)
                print(
                    f"[{symbol}] {result['status']} records={len(result.get('records') or [])} "
                    f"elapsed={result.get('elapsed_seconds')}s",
                    flush=True,
                )

    records = [record for result in results for record in result.get("records") or []]
    summary = _summarize(records)
    payload = {
        "report_version": "gate_ablation_validation_v1",
        "research_only": True,
        "official_validation": False,
        "production_profile_changed": False,
        "started_at": started.isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "as_of": as_of.isoformat(),
        "configuration": {
            "symbols": symbols,
            "timeframe": args.timeframe,
            "signals": signals,
            "limit": args.limit,
            "train_size": args.train_size,
            "test_size": args.test_size,
            "step_size": args.step_size,
            "mode": "EXPANDING",
            "profiles": {name: PROFILE_SPECS[name] for name in profiles},
        },
        "worker_results": results,
        "records": records,
        "summary": summary,
        "strict_regime_distribution": _strict_regime_distribution(records),
        "conclusion": _conclusion(summary),
    }
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "gate_ablation_report.json"
    markdown_path = output_dir / "gate_ablation_report.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    markdown_path.write_text(_markdown(payload), encoding="utf-8")
    print(json.dumps({"json": str(json_path.resolve()), "markdown": str(markdown_path.resolve())}, indent=2))


def _run_symbol(arguments):
    started = time.perf_counter()
    symbol = arguments["symbol"]
    timeframe = arguments["timeframe"]
    as_of = datetime.fromisoformat(arguments["as_of"])
    _install_runtime_ablation_profiles()

    research_specs = [PROFILE_SPECS[name] for name in arguments["profiles"]]
    research_state_keys = {
        (spec.get("regime_detector"), spec.get("transition_policy"))
        for spec in research_specs
    }
    if (
        len(arguments["profiles"]) > 1
        and all(spec.get("regime_detector") for spec in research_specs)
        and len(research_state_keys) == 1
    ):
        first_name = arguments["profiles"][0]
        first_spec = PROFILE_SPECS[first_name]
        first_results = {}
        for side in arguments["signals"]:
            first_results[side] = trade_simulator.execute_walk_forward(
                symbol,
                timeframe,
                side,
                limit=arguments["limit"],
                train_size=arguments["train_size"],
                test_size=arguments["test_size"],
                step_size=arguments["step_size"],
                mode="EXPANDING",
                strategy="SIGNAL_GATED",
                as_of_timestamp=as_of,
                min_confidence=first_spec["min_confidence"],
                regime_detector=_regime_detector(first_spec),
                transition_policy=_transition_policy(first_spec),
                research_label=first_name,
                research_gate_profile=first_spec.get("research_gate_profile"),
                risk_min_confidence=first_spec.get("risk_min_confidence"),
                risk_confidence_scope=first_spec.get("risk_confidence_scope"),
            )
        context_key = (
            *trade_simulator._frozen_replay_context_key(
                symbol,
                timeframe,
                arguments["limit"],
                as_of,
            ),
            _regime_detector(first_spec).__name__,
            getattr(
                _transition_policy(first_spec),
                "__name__",
                "production_hysteresis",
            ),
            _risk_min_confidence_key(first_spec),
            _risk_confidence_scope_key(first_spec),
        )
        base_context = trade_simulator._FROZEN_REPLAY_CONTEXT_CACHE[context_key]
        records = []
        contexts = {_research_context_key(first_spec): base_context}
        for profile_index, profile_name in enumerate(arguments["profiles"]):
            spec = PROFILE_SPECS[profile_name]
            context = contexts.get(_research_context_key(spec))
            if context is None:
                context = _build_research_context(
                    base_context,
                    symbol=symbol,
                    timeframe=timeframe,
                    spec=spec,
                )
                contexts[_research_context_key(spec)] = context
            for side in arguments["signals"]:
                result = (
                    first_results[side]
                    if profile_index == 0
                    else _run_ablation(
                        context,
                        symbol=symbol,
                        timeframe=timeframe,
                        side=side,
                        spec=spec,
                        arguments=arguments,
                        as_of=as_of,
                    )
                )
                records.append(
                    _record(symbol, timeframe, side, profile_name, spec, result)
                )
        return {
            "symbol": symbol,
            "status": "COMPLETED",
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "records": records,
        }

    if all(PROFILE_SPECS[name].get("regime_detector") for name in arguments["profiles"]):
        records = []
        for profile_name in arguments["profiles"]:
            spec = PROFILE_SPECS[profile_name]
            for side in arguments["signals"]:
                result = trade_simulator.execute_walk_forward(
                    symbol,
                    timeframe,
                    side,
                    limit=arguments["limit"],
                    train_size=arguments["train_size"],
                    test_size=arguments["test_size"],
                    step_size=arguments["step_size"],
                    mode="EXPANDING",
                    strategy="SIGNAL_GATED",
                    as_of_timestamp=as_of,
                    min_confidence=spec["min_confidence"],
                    regime_detector=_regime_detector(spec),
                    transition_policy=_transition_policy(spec),
                    research_label=profile_name,
                    research_gate_profile=spec.get("research_gate_profile"),
                    risk_min_confidence=spec.get("risk_min_confidence"),
                    risk_confidence_scope=spec.get("risk_confidence_scope"),
                )
                records.append(
                    _record(symbol, timeframe, side, profile_name, spec, result)
                )
        return {
            "symbol": symbol,
            "status": "COMPLETED",
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "records": records,
        }

    # The first strict call builds and caches the frozen point-in-time context.
    strict_results = {}
    for side in arguments["signals"]:
        strict_results[side] = trade_simulator.execute_walk_forward(
            symbol,
            timeframe,
            side,
            limit=arguments["limit"],
            train_size=arguments["train_size"],
            test_size=arguments["test_size"],
            step_size=arguments["step_size"],
            mode="EXPANDING",
            strategy="SIGNAL_GATED",
            as_of_timestamp=as_of,
        )

    context_key = trade_simulator._frozen_replay_context_key(
        symbol,
        timeframe,
        arguments["limit"],
        as_of,
    )
    context = trade_simulator._FROZEN_REPLAY_CONTEXT_CACHE[context_key]
    records = []
    research_contexts = {}
    for profile_name in arguments["profiles"]:
        spec = PROFILE_SPECS[profile_name]
        profile_context = context
        if spec.get("regime_detector"):
            profile_context = research_contexts.get(spec["regime_detector"])
            if profile_context is None:
                profile_context = _build_research_context(
                    context,
                    symbol=symbol,
                    timeframe=timeframe,
                    spec=spec,
                )
                research_contexts[spec["regime_detector"]] = profile_context
        for side in arguments["signals"]:
            if profile_name == "STRICT_BASELINE":
                result = strict_results[side]
            else:
                result = _run_ablation(
                    profile_context,
                    symbol=symbol,
                    timeframe=timeframe,
                    side=side,
                    spec=spec,
                    arguments=arguments,
                    as_of=as_of,
                )
            records.append(_record(symbol, timeframe, side, profile_name, spec, result))
    return {
        "symbol": symbol,
        "status": "COMPLETED",
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "records": records,
    }


def _build_research_context(context, *, symbol, timeframe, spec):
    detector = _regime_detector(spec)
    resolver = trade_simulator._build_in_memory_stack_resolver(
        symbol,
        context["stack_candles"],
        derivative_history=context["derivative_history"],
        feature_timeframe=timeframe,
        regime_detector=detector,
        transition_policy=_transition_policy(spec),
        risk_min_confidence=spec.get("risk_min_confidence"),
        risk_confidence_scope=spec.get("risk_confidence_scope"),
        stateful_timelines=getattr(
            context.get("stack_resolver"),
            "stateful_timelines",
            None,
        ),
        stack_cache=getattr(context.get("stack_resolver"), "stack_cache", None),
    )
    return {
        **context,
        "stack_resolver": resolver,
        "feature_resolver": resolver.feature_resolver,
    }


def _run_ablation(context, *, symbol, timeframe, side, spec, arguments, as_of):
    decision_cache = {}

    def runner(items, requested_side, **options):
        return run_filtered_replay(
            items,
            requested_side,
            feature_resolver=context["feature_resolver"],
            stack_resolver=context["stack_resolver"],
            initial_capital=options["initial_capital"],
            position_size_percent=options["position_size_percent"],
            min_confidence=spec["min_confidence"],
            stop_atr_multiple=options["stop_percent"],
            target_atr_multiple=options["target_percent"],
            cooldown_candles=3,
            fee_bps=options["fee_bps"],
            slippage_bps=options["slippage_bps"],
            gate_profile=spec["profile"],
            regime_detector=_regime_detector(spec),
            timeframe_minutes=TIMEFRAME_MINUTES[timeframe],
            mark_price_records=context["derivative_history"].get("mark_prices"),
            decision_cache=decision_cache,
        )

    return run_walk_forward(
        context["candles"],
        side,
        timeframe=timeframe,
        train_size=arguments["train_size"],
        test_size=arguments["test_size"],
        step_size=arguments["step_size"],
        mode="EXPANDING",
        min_train_trades=3,
        backtest_runner=runner,
        strategy_name=f"RESEARCH_{spec['profile']}_V1",
        strategy_metadata={
            "mode": "GATE_ABLATION_RESEARCH",
            "gate_profile": spec["profile"],
            "min_confidence": spec["min_confidence"],
            "risk_min_confidence": spec.get("risk_min_confidence", 65),
            "risk_confidence_scope": spec.get(
                "risk_confidence_scope", "PRODUCTION_ALL"
            ),
            "production_eligible": False,
            "as_of_timestamp": as_of.isoformat(),
        },
    )


def _install_runtime_ablation_profiles():
    strict = dict(GATE_PROFILES["STRICT"])
    GATE_PROFILES["ABLATION_NO_DECISION_CHAIN"] = {
        **strict,
        "enforce_decision_chain": False,
    }
    GATE_PROFILES["ABLATION_NO_REGIME_REQUIREMENT"] = {
        **strict,
        "long_regime_required": False,
        "short_regime_required": False,
    }


def _regime_detector(spec):
    if spec.get("regime_detector") == "MOMENTUM_BOUNDARY_ALIGNMENT_RESEARCH":
        return detect_regime_momentum_boundary_research
    return detect_regime


def _transition_policy(spec):
    if spec.get("transition_policy") == "DIRECTION_AWARE_HYSTERESIS_RESEARCH":
        return direction_aware_transition_research
    return None


def _risk_min_confidence_key(spec):
    value = spec.get("risk_min_confidence")
    return "production_65" if value is None else f"research_{float(value):g}"


def _risk_confidence_scope_key(spec):
    return str(spec.get("risk_confidence_scope") or "PRODUCTION_ALL").upper()


def _research_context_key(spec):
    return (
        spec.get("regime_detector"),
        spec.get("transition_policy"),
        _risk_min_confidence_key(spec),
        _risk_confidence_scope_key(spec),
    )


def _record(symbol, timeframe, side, profile_name, spec, result):
    oos = result.get("out_of_sample") or {}
    diagnostics = oos.get("gate_diagnostics") or {}
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "side": side,
        "profile": profile_name,
        "description": spec["description"],
        "regime_detector": spec.get("regime_detector", "PRODUCTION_DEFAULT"),
        "transition_policy": spec.get("transition_policy", "PRODUCTION_DEFAULT"),
        "risk_min_confidence": spec.get("risk_min_confidence", 65),
        "risk_confidence_scope": spec.get(
            "risk_confidence_scope", "PRODUCTION_ALL"
        ),
        "production_eligible": spec["production_eligible"],
        "validation_status": result.get("validation_status"),
        "fold_count": result.get("fold_count"),
        "evaluated_decisions": diagnostics.get("evaluated_decisions", 0),
        "signals": diagnostics.get("signals") or {},
        "rejections": diagnostics.get("rejections") or {},
        "regimes": diagnostics.get("regimes") or {},
        "regime_sources": diagnostics.get("regime_sources") or {},
        "regime_percentages": diagnostics.get("regime_percentages") or {},
        "regime_direction_percentages": diagnostics.get("regime_direction_percentages") or {},
        "independent_gate_pass_counts": diagnostics.get(
            "independent_gate_pass_counts"
        )
        or {},
        "independent_gate_pass_percentages": diagnostics.get(
            "independent_gate_pass_percentages"
        )
        or {},
        "rejection_combinations": diagnostics.get("rejection_combinations") or {},
        "feature_score_distributions": diagnostics.get(
            "feature_score_distributions"
        )
        or {},
        "master_signal_diagnostics": diagnostics.get("master_signal_diagnostics")
        or {},
        "directional_entry_funnel": diagnostics.get("directional_entry_funnel")
        or {},
        "oos_trades": oos.get("total_trades", 0),
        "oos_trade_regimes": dict(
            Counter(
                str(trade.get("regime") or "UNKNOWN")
                for trade in (oos.get("trades") or ())
            )
        ),
        "oos_net_profit": oos.get("net_profit", 0),
        "oos_profit_factor": oos.get("profit_factor"),
        "oos_win_rate": oos.get("win_rate"),
        "oos_max_drawdown_percent": oos.get("max_drawdown_percent"),
        "oos_sharpe_ratio": oos.get("sharpe_ratio"),
    }


def _summarize(records):
    grouped = defaultdict(list)
    for record in records:
        grouped[(record["profile"], record["side"])].append(record)
    rows = []
    for (profile, side), items in sorted(grouped.items()):
        rejection_counts = Counter()
        for item in items:
            rejection_counts.update(item["rejections"])
        rows.append(
            {
                "profile": profile,
                "side": side,
                "scope_count": len(items),
                "scopes_with_trades": sum(item["oos_trades"] > 0 for item in items),
                "profitable_scopes": sum((item["oos_net_profit"] or 0) > 0 for item in items),
                "total_oos_trades": sum(item["oos_trades"] or 0 for item in items),
                "combined_independent_scope_net_profit": round(
                    sum(item["oos_net_profit"] or 0 for item in items), 2
                ),
                "worst_scope_drawdown_percent": max(
                    (item["oos_max_drawdown_percent"] or 0 for item in items),
                    default=0,
                ),
                "top_rejections": dict(rejection_counts.most_common(5)),
            }
        )
    return rows


def _strict_regime_distribution(records):
    # LONG and SHORT evaluate the same timestamps and therefore carry the same
    # regime distribution. Use one side to avoid double-counting observations.
    counts = Counter()
    for record in records:
        if record["profile"] == "STRICT_BASELINE" and record["side"] == "LONG":
            counts.update(record["regimes"])
    total = sum(counts.values())
    directions = Counter()
    for regime, count in counts.items():
        directions[regime_direction(regime)] += count
    percent = lambda value: round((value / total) * 100, 2) if total else 0
    return {
        "evaluated_decisions": total,
        "regimes": dict(sorted(counts.items())),
        "regime_percentages": {
            key: percent(value) for key, value in sorted(counts.items())
        },
        "directions": dict(sorted(directions.items())),
        "direction_percentages": {
            key: percent(value) for key, value in sorted(directions.items())
        },
    }


def _conclusion(summary):
    ablations = [row for row in summary if row["profile"] != "STRICT_BASELINE"]
    if not ablations:
        return {
            "status": "STRICT_SCORE_DIAGNOSTIC_ONLY",
            "production_action": "KEEP_STRICT_UNCHANGED",
            "interpretation": (
                "Only the strict baseline was executed to collect score distributions "
                "and rejection co-occurrence."
            ),
            "next_action": (
                "Use the recorded score and overlap evidence to define research-only "
                "conditional-entry candidates."
            ),
        }
    if ablations and all(row["total_oos_trades"] == 0 for row in ablations):
        return {
            "status": "NO_SINGLE_GATE_ABLATION_RESTORED_COVERAGE",
            "production_action": "KEEP_STRICT_UNCHANGED",
            "interpretation": (
                "The zero-trade result is caused by overlapping gate conditions; "
                "confidence, regime, and decision-chain gates are not individually decisive."
            ),
            "next_action": (
                "Measure point-in-time feature-score distributions and rejection "
                "co-occurrence, then test explicit entry confirmation within directional "
                "pullback/range regimes as research-only candidates."
            ),
        }
    return {
        "status": "ABLATION_GENERATED_COVERAGE",
        "production_action": "REQUIRE_BROADER_VALIDATION_BEFORE_ANY_CHANGE",
        "interpretation": "At least one isolated ablation generated trades.",
        "next_action": "Evaluate profitability, stability, and untouched-symbol evidence.",
    }


def _markdown(payload):
    rows = []
    for row in payload["summary"]:
        rows.append(
            f"| {row['profile']} | {row['side']} | {row['scopes_with_trades']}/{row['scope_count']} "
            f"| {row['profitable_scopes']} | {row['total_oos_trades']} "
            f"| {row['combined_independent_scope_net_profit']:.2f} "
            f"| {row['worst_scope_drawdown_percent']:.2f}% |"
        )
    regime_rows = [
        f"| {regime} | {count} | {payload['strict_regime_distribution']['regime_percentages'][regime]:.2f}% |"
        for regime, count in sorted(
            payload["strict_regime_distribution"]["regimes"].items(),
            key=lambda item: item[1],
            reverse=True,
        )
    ]
    conclusion = payload["conclusion"]
    return "\n".join(
        [
            "# Research-Only Gate Ablation Report",
            "",
            "This compact study changes one strict gate at a time. It is not official validation and cannot promote a profile to production.",
            "",
            f"Frozen cutoff: `{payload['as_of']}`.",
            "",
            "| Profile | Side | Scopes with trades | Profitable scopes | OOS trades | Independent-scope net profit | Worst drawdown |",
            "|---|---|---:|---:|---:|---:|---:|",
            *rows,
            "",
            "`Independent-scope net profit` is diagnostic only; each symbol/side starts with its own capital and the values do not represent a combined portfolio.",
            "",
            "## Strict regime distribution",
            "",
            "Regime is calculated independently for the 4h decision timeframe in this study. LONG and SHORT use the same regime observations, so the table counts each timestamp once.",
            "",
            "| Regime | Decisions | Share |",
            "|---|---:|---:|",
            *regime_rows,
            "",
            "Direction totals: "
            + ", ".join(
                f"{key} {value:.2f}%"
                for key, value in payload["strict_regime_distribution"]["direction_percentages"].items()
            )
            + ".",
            "",
            "## Conclusion",
            "",
            f"Status: `{conclusion['status']}`.",
            "",
            conclusion["interpretation"],
            "",
            f"Production action: `{conclusion['production_action']}`.",
            "",
            f"Next action: {conclusion['next_action']}",
            "",
        ]
    )


def _csv(value):
    return tuple(item.strip().upper() for item in str(value).split(",") if item.strip())


if __name__ == "__main__":
    main()
