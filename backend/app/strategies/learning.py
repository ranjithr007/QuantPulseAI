"""Automatic, paper-only strategy evaluation and immutable candidates."""

from __future__ import annotations

import copy
import json
from collections import defaultdict
from sqlalchemy.exc import SQLAlchemyError

from app.database.models.strategy_learning import StrategyLearningEvaluation
from app.database.models.strategy_learning import StrategyVersionConfig
from app.database.models.strategy_shadow_trade import StrategyShadowTrade
from app.database.models.point_in_time_snapshots import DecisionSnapshot
from app.paper_trading.inr_sizing import PAPER_CAPITAL_INR
from app.repositories.notification_repository import NotificationRepository
from app.strategies.registry import STRATEGY_REGISTRY


MINIMUM_CLOSED_TRADES = 30
REEVALUATION_STEP = 10
EVALUATION_WINDOW_SIZE = 30
ACTIVE_CANDIDATE_STATUSES = {"COLLECTING", "PAPER_CHAMPION"}


def strategy_definitions(db, strategy_id=None):
    normalized = str(strategy_id or "").upper() or None
    bases = [
        definition
        for definition in STRATEGY_REGISTRY.values()
        if normalized is None or definition["id"] == normalized
    ]
    definitions = [dict(item) for item in bases]
    if not bases:
        return definitions
    try:
        configs = (
            db.query(StrategyVersionConfig)
            .filter(
                StrategyVersionConfig.strategy_id.in_([item["id"] for item in bases])
            )
            .filter(StrategyVersionConfig.status.in_(ACTIVE_CANDIDATE_STATUSES))
            .order_by(
                StrategyVersionConfig.created_at.asc(),
                StrategyVersionConfig.id.asc(),
            )
            .all()
        )
    except SQLAlchemyError:
        db.rollback()
        configs = []
    for config in configs:
        base = STRATEGY_REGISTRY.get(config.strategy_id)
        if base is not None:
            definitions.append(_candidate_definition(base, config))
    return definitions


def resolve_strategy_definition(db, strategy_id, strategy_version=None):
    base = STRATEGY_REGISTRY.get(str(strategy_id or "").upper())
    if base is None:
        return None
    if not strategy_version or strategy_version == base["version"] or db is None:
        return dict(base)
    try:
        config = (
            db.query(StrategyVersionConfig)
            .filter(StrategyVersionConfig.strategy_id == base["id"])
            .filter(StrategyVersionConfig.version == strategy_version)
            .first()
        )
    except SQLAlchemyError:
        db.rollback()
        return None
    return _candidate_definition(base, config) if config is not None else None


def active_candidate_definitions(db):
    return [
        item
        for item in strategy_definitions(db)
        if item.get("strategy_type") == "AUTO_CANDIDATE"
    ]


def apply_learning_parameters(payload, definition):
    """Apply bounded entry filters without changing the scanned evidence."""

    parameters = definition.get("learning_parameters") or {}
    candidate = copy.deepcopy(payload)
    trigger = candidate.get("trigger") or {}
    plan = candidate.get("trade_plan") or {}
    timeframe = str(
        trigger.get("entry_timeframe") or plan.get("entry_timeframe") or ""
    ).lower()
    selected = next(
        (
            item
            for item in candidate.get("timeframes") or []
            if str(item.get("timeframe") or "").lower() == timeframe
        ),
        {},
    )
    regime = str(
        selected.get("regime")
        or plan.get("regime")
        or (candidate.get("confirmation") or {}).get("regime")
        or ""
    ).upper()
    confidence = float(
        (candidate.get("confirmation") or {}).get("confidence")
        or selected.get("confidence")
        or plan.get("confidence")
        or 0
    )
    symbol = str(candidate.get("symbol") or "").upper()
    blocked = []
    minimum_confidence = float(parameters.get("minimum_confidence") or 0)
    if confidence < minimum_confidence:
        blocked.append(
            f"Automatic candidate requires {minimum_confidence:.0f}% confidence"
        )
    allowed_timeframes = parameters.get("allowed_timeframes") or []
    if allowed_timeframes and timeframe not in allowed_timeframes:
        blocked.append(f"{timeframe or 'Selected timeframe'} failed prior evidence")
    allowed_regimes = parameters.get("allowed_regimes") or []
    if allowed_regimes and regime not in allowed_regimes:
        blocked.append(f"{regime or 'Selected regime'} failed prior evidence")
    if symbol in (parameters.get("blocked_symbols") or []):
        blocked.append(f"{symbol} is quarantined by prior paper evidence")
    if parameters.get("require_fresh_inputs"):
        freshness = selected.get("freshness") or {}
        if freshness.get("is_stale") is True or selected.get("status") in {
            "STALE",
            "NO_DATA",
        }:
            blocked.append("Automatic candidate requires fresh selected-timeframe inputs")

    if blocked:
        candidate["trigger"] = {
            **trigger,
            "status": "WAIT",
            "side": None,
            "reason": blocked[0],
        }
        validation = candidate.get("trade_plan_validation") or {}
        candidate["trade_plan_validation"] = {
            **validation,
            "is_valid": False,
            "errors": list(dict.fromkeys(blocked + list(validation.get("errors") or []))),
        }
    candidate["strategy_learning"] = {
        "candidate_version": definition["version"],
        "source_evaluation_id": definition.get("source_evaluation_id"),
        "parameters": parameters,
        "blocked_reasons": blocked,
        "paper_only": True,
    }
    return candidate


def candidate_rearm_blocker(db, definition, history, candidate):
    """Require a new selected-timeframe candle after a same-side stop."""

    parameters = definition.get("learning_parameters") or {}
    if not parameters.get("require_signal_rearm"):
        return None
    symbol = str(candidate.get("symbol") or "").upper()
    side = str(candidate.get("side") or "").upper()
    stopped = [
        item
        for item in history
        if str(item.symbol or "").upper() == symbol
        and str(item.side or "").upper() == side
        and str(item.status or "").upper() == "CLOSED"
        and str(item.exit_reason or "").upper() in {"STOP", "STOP_LOSS"}
    ]
    if not stopped:
        return None
    previous = max(stopped, key=lambda item: (item.closed_at or item.created_at, item.id))
    plan = candidate.get("trade_plan") or {}
    snapshot_ids = [
        value
        for value in (
            previous.strategy_decision_snapshot_id,
            plan.get("strategy_decision_snapshot_id"),
        )
        if value is not None
    ]
    snapshots = {
        item.id: item
        for item in db.query(DecisionSnapshot)
        .filter(DecisionSnapshot.id.in_(snapshot_ids))
        .all()
    }
    old_snapshot = snapshots.get(previous.strategy_decision_snapshot_id)
    new_snapshot = snapshots.get(plan.get("strategy_decision_snapshot_id"))
    if old_snapshot is None or new_snapshot is None:
        return "Automatic candidate is waiting for verifiable signal re-arm evidence"
    if new_snapshot.source_timestamp <= old_snapshot.source_timestamp:
        return "Automatic candidate is waiting for a newly closed timeframe candle"
    return None


def evaluate_due_strategy_versions(db):
    """Evaluate due 30-trade windows and create paper-only challengers."""

    evaluated = []
    created_candidates = []
    for definition in strategy_definitions(db):
        trades = (
            db.query(StrategyShadowTrade)
            .filter(StrategyShadowTrade.strategy_id == definition["id"])
            .filter(StrategyShadowTrade.strategy_version == definition["version"])
            .filter(StrategyShadowTrade.status == "CLOSED")
            .filter(StrategyShadowTrade.symbol.notlike("QA%"))
            .order_by(
                StrategyShadowTrade.closed_at.asc(),
                StrategyShadowTrade.id.asc(),
            )
            .all()
        )
        milestone = evaluation_milestone(len(trades))
        if milestone is None or _evaluation_exists(db, definition, milestone):
            continue
        report = analyze_strategy_trades(trades, window_size=EVALUATION_WINDOW_SIZE)
        recommendations = recommend_candidate_parameters(definition, report)
        config = _config_for_definition(db, definition)
        benchmark_passed = (
            _beats_current_benchmark(db, config, report["metrics"])
            if config is not None and report["promotion_candidate"]
            else True
        )
        accepted = report["promotion_candidate"] and benchmark_passed
        report["gates"]["beats_current_benchmark"] = benchmark_passed
        evaluation = StrategyLearningEvaluation(
            strategy_id=definition["id"],
            strategy_version=definition["version"],
            milestone=milestone,
            window_size=EVALUATION_WINDOW_SIZE,
            closed_trade_count=len(trades),
            status=(
                "PROMOTION_CANDIDATE"
                if accepted
                else "CHANGES_REQUIRED"
            ),
            metrics_json=json.dumps(
                {**report["metrics"], "gates": report["gates"]},
                sort_keys=True,
            ),
            diagnostics_json=json.dumps(report["diagnostics"], sort_keys=True),
            recommended_changes_json=json.dumps(recommendations, sort_keys=True),
        )
        db.add(evaluation)
        db.flush()
        evaluated.append(evaluation)

        if config is not None:
            if accepted:
                prior_champions = (
                    db.query(StrategyVersionConfig)
                    .filter(StrategyVersionConfig.strategy_id == config.strategy_id)
                    .filter(StrategyVersionConfig.status == "PAPER_CHAMPION")
                    .filter(StrategyVersionConfig.version != config.version)
                    .all()
                )
                for champion in prior_champions:
                    champion.status = "SUPERSEDED"
                    champion.official_paper_enabled = False
                config.status = "PAPER_CHAMPION"
                config.official_paper_enabled = True
            else:
                config.status = "FAILED"
                config.official_paper_enabled = False

        candidate = None
        if not accepted and not _has_collecting_candidate(
            db, definition["id"]
        ):
            candidate = _create_candidate(db, definition, evaluation, recommendations)
            evaluation.candidate_version = candidate.version
            created_candidates.append(candidate)

        _notify_learning_evaluation(
            db,
            definition=definition,
            evaluation=evaluation,
            report=report,
            candidate=candidate,
            config=config,
            accepted=accepted,
        )

    db.commit()
    return {
        "status": "READY",
        "evaluated_count": len(evaluated),
        "created_candidate_count": len(created_candidates),
        "evaluations": [evaluation_payload(item) for item in evaluated],
        "candidates": [version_config_payload(item) for item in created_candidates],
        "live_execution_enabled": False,
    }


def analyze_strategy_trades(trades, window_size=EVALUATION_WINDOW_SIZE):
    closed = sorted(
        (item for item in trades if str(item.status).upper() == "CLOSED"),
        key=lambda item: (item.closed_at or item.created_at, item.id),
    )
    window = closed[-window_size:]
    metrics = _trade_metrics(window)
    gates = {
        "sample_size": len(window) >= MINIMUM_CLOSED_TRADES,
        "win_rate": metrics["win_rate"] >= 55.0,
        "profit_factor": metrics["profit_factor"] >= 1.30,
        "cost_adjusted_expectancy": metrics["expectancy_inr"] > 0,
        "targets_exceed_initial_stops": (
            metrics["target_successes"] > metrics["initial_stop_failures"]
        ),
        "maximum_drawdown": metrics["max_drawdown_percent"] <= 10.0,
    }
    return {
        "metrics": metrics,
        "diagnostics": {
            "by_symbol": _group_metrics(window, "symbol"),
            "by_timeframe": _group_metrics(window, "entry_timeframe"),
            "by_regime": _group_metrics(window, "regime"),
            "by_side": _group_metrics(window, "side"),
        },
        "gates": gates,
        "promotion_candidate": all(gates.values()),
        "authorizes_live_execution": False,
    }


def recommend_candidate_parameters(definition, report):
    diagnostics = report["diagnostics"]
    healthy_timeframes = _healthy_groups(diagnostics["by_timeframe"])
    healthy_regimes = _healthy_groups(diagnostics["by_regime"])
    blocked_symbols = [
        name
        for name, metrics in diagnostics["by_symbol"].items()
        if metrics["closed_trades"] >= 5
        and metrics["net_pnl_inr"] < 0
        and metrics["initial_stop_failures"] >= metrics["target_successes"]
    ]
    parameters = {
        "minimum_confidence": float(definition.get("signal_threshold") or 40.0),
        "require_fresh_inputs": True,
        "require_signal_rearm": True,
        "blocked_symbols": sorted(blocked_symbols),
        "paper_only": True,
    }
    if healthy_timeframes:
        parameters["allowed_timeframes"] = healthy_timeframes
    if healthy_regimes:
        parameters["allowed_regimes"] = healthy_regimes
    return parameters


def evaluation_milestone(closed_trade_count):
    if closed_trade_count < MINIMUM_CLOSED_TRADES:
        return None
    return MINIMUM_CLOSED_TRADES + (
        (closed_trade_count - MINIMUM_CLOSED_TRADES) // REEVALUATION_STEP
    ) * REEVALUATION_STEP


def latest_evaluations(db, definitions):
    result = {}
    for definition in definitions:
        try:
            row = (
                db.query(StrategyLearningEvaluation)
                .filter(StrategyLearningEvaluation.strategy_id == definition["id"])
                .filter(
                    StrategyLearningEvaluation.strategy_version
                    == definition["version"]
                )
                .order_by(
                    StrategyLearningEvaluation.milestone.desc(),
                    StrategyLearningEvaluation.id.desc(),
                )
                .first()
            )
        except SQLAlchemyError:
            db.rollback()
            return {}
        if row is not None:
            result[(definition["id"], definition["version"])] = evaluation_payload(row)
    return result


def evaluation_payload(row):
    return {
        "id": row.id,
        "strategy_id": row.strategy_id,
        "strategy_version": row.strategy_version,
        "milestone": row.milestone,
        "window_size": row.window_size,
        "closed_trade_count": row.closed_trade_count,
        "status": row.status,
        "metrics": _json(row.metrics_json),
        "diagnostics": _json(row.diagnostics_json),
        "recommended_changes": _json(row.recommended_changes_json),
        "candidate_version": row.candidate_version,
        "created_at": row.created_at,
        "authorizes_live_execution": False,
    }


def version_config_payload(row):
    return {
        "id": row.id,
        "strategy_id": row.strategy_id,
        "version": row.version,
        "base_version": row.base_version,
        "decision_version": row.decision_version,
        "status": row.status,
        "parameters": _json(row.parameters_json),
        "official_paper_enabled": bool(row.official_paper_enabled),
        "live_execution_enabled": False,
    }


def _trade_metrics(trades):
    closed = len(trades)
    wins = sum(1 for item in trades if float(item.realized_pnl_inr or 0) > 0)
    target_successes = sum(1 for item in trades if item.target1_hit_at is not None)
    initial_stops = sum(
        1
        for item in trades
        if str(item.exit_reason or "").upper() in {"STOP", "STOP_LOSS"}
        and item.target1_hit_at is None
    )
    protected_stops = sum(
        1
        for item in trades
        if str(item.exit_reason or "").upper() in {"STOP", "STOP_LOSS"}
        and item.target1_hit_at is not None
    )
    pnl = [float(item.realized_pnl_inr or 0) for item in trades]
    gains = sum(max(value, 0) for value in pnl)
    losses = abs(sum(min(value, 0) for value in pnl))
    net = sum(pnl)
    return {
        "closed_trades": closed,
        "wins": wins,
        "losses": closed - wins,
        "win_rate": round(wins / closed * 100, 2) if closed else 0.0,
        "target_successes": target_successes,
        "target2_hits": sum(
            1 for item in trades if str(item.exit_reason or "").upper() == "TARGET2"
        ),
        "initial_stop_failures": initial_stops,
        "protected_stop_exits": protected_stops,
        "target_success_rate": round(target_successes / closed * 100, 2)
        if closed
        else 0.0,
        "initial_stop_failure_rate": round(initial_stops / closed * 100, 2)
        if closed
        else 0.0,
        "net_pnl_inr": round(net, 2),
        "expectancy_inr": round(net / closed, 2) if closed else 0.0,
        "profit_factor": round(gains / losses, 4)
        if losses
        else (999.0 if gains else 0.0),
        "max_drawdown_percent": _max_drawdown_percent(pnl),
        "fees_percent": round(sum(float(item.fees_percent or 0) for item in trades), 4),
        "funding_cost_percent": round(
            sum(float(item.funding_cost_percent or 0) for item in trades), 4
        ),
    }


def _group_metrics(trades, attribute):
    grouped = defaultdict(list)
    for trade in trades:
        grouped[str(getattr(trade, attribute, None) or "UNKNOWN").upper()].append(trade)
    return {name: _trade_metrics(items) for name, items in sorted(grouped.items())}


def _healthy_groups(groups):
    return sorted(
        name.lower() if name in {"1H", "2H", "4H", "1D"} else name
        for name, metrics in groups.items()
        if name != "UNKNOWN"
        and metrics["closed_trades"] >= 5
        and metrics["net_pnl_inr"] > 0
        and metrics["target_successes"] > metrics["initial_stop_failures"]
    )


def _max_drawdown_percent(pnl_values):
    equity = float(PAPER_CAPITAL_INR)
    peak = equity
    maximum = 0.0
    for pnl in pnl_values:
        equity += pnl
        peak = max(peak, equity)
        if peak > 0:
            maximum = max(maximum, (peak - equity) / peak * 100)
    return round(maximum, 4)


def _candidate_definition(base, config):
    parameters = _json(config.parameters_json)
    return {
        **base,
        "version": config.version,
        "decision_version": config.decision_version,
        "name": f"{base['name']} Candidate",
        "strategy_type": "AUTO_CANDIDATE",
        "status": (
            "ACTIVE" if config.status in ACTIVE_CANDIDATE_STATUSES else "PAUSED"
        ),
        "execution_scope": "PAPER_ONLY",
        "official_execution_enabled": bool(config.official_paper_enabled),
        "learning_status": config.status,
        "learning_parameters": parameters,
        "source_evaluation_id": config.source_evaluation_id,
        "live_execution_enabled": False,
    }


def _evaluation_exists(db, definition, milestone):
    return (
        db.query(StrategyLearningEvaluation.id)
        .filter(StrategyLearningEvaluation.strategy_id == definition["id"])
        .filter(StrategyLearningEvaluation.strategy_version == definition["version"])
        .filter(StrategyLearningEvaluation.milestone == milestone)
        .first()
        is not None
    )


def _config_for_definition(db, definition):
    return (
        db.query(StrategyVersionConfig)
        .filter(StrategyVersionConfig.strategy_id == definition["id"])
        .filter(StrategyVersionConfig.version == definition["version"])
        .first()
    )


def _has_collecting_candidate(db, strategy_id):
    return (
        db.query(StrategyVersionConfig.id)
        .filter(StrategyVersionConfig.strategy_id == strategy_id)
        .filter(StrategyVersionConfig.status == "COLLECTING")
        .first()
        is not None
    )


def _create_candidate(db, definition, evaluation, parameters):
    root = STRATEGY_REGISTRY[definition["id"]]
    suffix = f"auto_m{evaluation.milestone}_{evaluation.id}"
    version = f"{root['id'].lower()}_{suffix}"
    decision_version = f"{root['id'].lower()}_decision_{suffix}"
    candidate = StrategyVersionConfig(
        strategy_id=root["id"],
        version=version[:50],
        base_version=root["version"],
        decision_version=decision_version[:40],
        status="COLLECTING",
        parameters_json=json.dumps(parameters, sort_keys=True),
        source_evaluation_id=evaluation.id,
        paper_execution_enabled=True,
        official_paper_enabled=False,
        live_execution_enabled=False,
    )
    db.add(candidate)
    db.flush()
    return candidate


def _notify_learning_evaluation(
    db,
    *,
    definition,
    evaluation,
    report,
    candidate,
    config,
    accepted,
):
    metrics = report["metrics"]
    if accepted and config is not None:
        event_type = "STRATEGY_PAPER_CHAMPION"
        severity = "SUCCESS"
        title = f"{definition['name']} passed paper champion review"
    elif candidate is not None and config is not None:
        event_type = "STRATEGY_CANDIDATE_REPLACED"
        severity = "WARNING"
        title = f"{definition['name']} needs another paper revision"
    elif candidate is not None:
        event_type = "STRATEGY_CANDIDATE_CREATED"
        severity = "WARNING"
        title = f"{definition['name']} paper candidate created"
    elif accepted:
        event_type = "STRATEGY_LEARNING_PASSED"
        severity = "SUCCESS"
        title = f"{definition['name']} passed its learning review"
    else:
        event_type = "STRATEGY_LEARNING_FAILED"
        severity = "WARNING"
        title = f"{definition['name']} learning review needs changes"

    candidate_version = (
        candidate.version
        if candidate is not None
        else evaluation.candidate_version
    )
    message = (
        f"Milestone {evaluation.milestone} using the latest "
        f"{evaluation.window_size} closed trades: "
        f"win rate {float(metrics.get('win_rate') or 0):.1f}%, "
        f"targets {int(metrics.get('target_successes') or 0)}, "
        f"initial stops {int(metrics.get('initial_stop_failures') or 0)}, "
        f"profit factor {float(metrics.get('profit_factor') or 0):.2f}, "
        f"expectancy INR {float(metrics.get('expectancy_inr') or 0):+,.2f}."
    )
    if candidate_version:
        message += f" Paper candidate: {candidate_version}."

    NotificationRepository().create(
        db,
        event_key=f"strategy_learning:{evaluation.id}:{event_type}",
        category="STRATEGY",
        event_type=event_type,
        severity=severity,
        title=title,
        message=message,
        metadata={
            "strategyId": definition["id"],
            "strategyVersion": definition["version"],
            "milestone": evaluation.milestone,
            "windowSize": evaluation.window_size,
            "status": evaluation.status,
            "candidateVersion": candidate_version,
            "gates": report.get("gates") or {},
            "liveExecutionEnabled": False,
        },
    )


def _beats_current_benchmark(db, config, candidate_metrics):
    champion = (
        db.query(StrategyVersionConfig)
        .filter(StrategyVersionConfig.strategy_id == config.strategy_id)
        .filter(StrategyVersionConfig.status == "PAPER_CHAMPION")
        .filter(StrategyVersionConfig.version != config.version)
        .order_by(StrategyVersionConfig.updated_at.desc(), StrategyVersionConfig.id.desc())
        .first()
    )
    benchmark_version = champion.version if champion is not None else config.base_version
    benchmark = (
        db.query(StrategyLearningEvaluation)
        .filter(StrategyLearningEvaluation.strategy_id == config.strategy_id)
        .filter(StrategyLearningEvaluation.strategy_version == benchmark_version)
        .order_by(
            StrategyLearningEvaluation.created_at.desc(),
            StrategyLearningEvaluation.id.desc(),
        )
        .first()
    )
    if benchmark is None:
        return False
    metrics = _json(benchmark.metrics_json)
    return bool(
        float(candidate_metrics.get("profit_factor") or 0)
        >= float(metrics.get("profit_factor") or 0)
        and float(candidate_metrics.get("expectancy_inr") or 0)
        >= float(metrics.get("expectancy_inr") or 0)
        and float(candidate_metrics.get("max_drawdown_percent") or 0)
        <= float(metrics.get("max_drawdown_percent") or 0)
    )


def _json(value):
    try:
        return json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
