import json
from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Query
from sqlalchemy import func

from app.database.models.paper_trade import PaperTrade
from app.database.models.point_in_time_snapshots import DecisionSnapshot
from app.database.models.risk_decision import RiskDecision
from app.database.models.strategy_shadow_trade import StrategyShadowTrade
from app.database.models.trade_plan import TradePlan
from app.database.sqlserver import SessionLocal
from app.paper_trading.evidence_scope import production_paper_trade_records
from app.paper_trading.inr_sizing import PAPER_CAPITAL_INR
from app.strategies.registry import STRATEGY_REGISTRY
from app.strategies.registry import strategy_definition


router = APIRouter(prefix="/strategies", tags=["Strategies"])


@router.get("/summary")
def get_strategy_summary(
    strategy_id: str | None = Query(default=None),
    since_days: int = Query(default=30, ge=1, le=3650),
    candidate_limit: int = Query(default=24, ge=1, le=200),
):
    normalized = str(strategy_id or "").upper() or None
    if normalized and normalized not in STRATEGY_REGISTRY:
        return {
            "source": "strategy_performance_v1",
            "status": "NOT_FOUND",
            "strategy_id": normalized,
            "records": [],
        }

    db = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(days=since_days)
        definitions = (
            [strategy_definition(normalized)]
            if normalized
            else list(STRATEGY_REGISTRY.values())
        )
        strategy_data = _load_strategy_data(db, definitions, cutoff)
        records = [
            _strategy_record_from_data(
                definition,
                strategy_data,
                cutoff,
                candidate_limit,
            )
            for definition in definitions
        ]
        return {
            "source": "strategy_performance_v1",
            "status": "READY",
            "execution_scope": "PAPER_ONLY",
            "since_days": since_days,
            "one_active_trade_per_symbol": True,
            "strategy_count": len(records),
            "comparison": _shadow_comparison(records),
            "records": records,
        }
    finally:
        db.close()


def _strategy_record(db, definition, cutoff, candidate_limit):
    strategy_data = _load_strategy_data(db, [definition], cutoff)
    return _strategy_record_from_data(
        definition,
        strategy_data,
        cutoff,
        candidate_limit,
    )


def _strategy_record_from_data(definition, strategy_data, cutoff, candidate_limit):
    key = (definition["id"], definition["version"])
    snapshots = strategy_data["snapshots"].get(key, [])
    plans = strategy_data["plans"].get(key, [])
    trades = strategy_data["paper_trades"].get(key, [])
    strategy_book_trades = strategy_data["strategy_paper_trades"].get(key, [])
    shadow_trades = [
        item for item in strategy_book_trades if item.created_at >= cutoff
    ]
    candidates = _latest_candidates(
        snapshots,
        plans,
        trades,
        strategy_book_trades,
        candidate_limit,
    )
    official_performance = _strategy_performance(trades)
    shadow_performance = _strategy_performance(shadow_trades)
    strategy_book_performance = _strategy_performance(strategy_book_trades)
    return {
        **definition,
        "coverage": {
            "decision_snapshots": len(snapshots),
            "trade_plans": len(plans),
            "risk_decisions": strategy_data["risk_counts"].get(key, 0),
            "paper_trades": len(trades),
            "shadow_trades": len(shadow_trades),
            "strategy_paper_trades": len(shadow_trades),
            "strategy_paper_lifetime_trades": len(strategy_book_trades),
            "eligible_signals": sum(
                1 for item in snapshots if str(item.decision).upper() == "ELIGIBLE"
            ),
            "blocked_signals": sum(
                1 for item in snapshots if str(item.decision).upper() == "BLOCKED"
            ),
        },
        # The headline comparison uses isolated shadow results because every
        # strategy receives the same opportunity to trade. Official results
        # contain only the one winner selected for the shared portfolio.
        "performance": shadow_performance,
        "shadow_performance": shadow_performance,
        "strategy_paper_performance": shadow_performance,
        "strategy_paper_lifetime_performance": strategy_book_performance,
        "strategy_paper_wallet": {
            "initial_capital_inr": PAPER_CAPITAL_INR,
            "realized_pnl_inr": strategy_book_performance["net_pnl_inr"],
            "wallet_balance_inr": round(
                PAPER_CAPITAL_INR + strategy_book_performance["net_pnl_inr"],
                2,
            ),
            "open_position_count": strategy_book_performance["open_trades"],
        },
        "strategy_paper_history": [
            _strategy_paper_trade_payload(item)
            for item in reversed(strategy_book_trades[-20:])
        ],
        "official_performance": official_performance,
        "forward_test_readiness": _forward_test_readiness(shadow_performance),
        "candidates": candidates,
    }


def _load_strategy_data(db, definitions, cutoff):
    """Load all strategy-summary evidence in five bounded database queries."""

    strategy_ids = [definition["id"] for definition in definitions]
    decision_versions = [
        definition["decision_version"] for definition in definitions
    ]
    if not strategy_ids:
        return {
            "snapshots": {},
            "plans": {},
            "risk_counts": {},
            "paper_trades": {},
            "strategy_paper_trades": {},
        }

    ranked_snapshot_ids = (
        db.query(
            DecisionSnapshot.id.label("snapshot_id"),
            func.row_number()
            .over(
                partition_by=(
                    DecisionSnapshot.strategy_id,
                    DecisionSnapshot.strategy_version,
                    DecisionSnapshot.decision_version,
                ),
                order_by=(
                    DecisionSnapshot.created_at.desc(),
                    DecisionSnapshot.id.desc(),
                ),
            )
            .label("strategy_rank"),
        )
        .filter(DecisionSnapshot.strategy_id.in_(strategy_ids))
        .filter(DecisionSnapshot.decision_version.in_(decision_versions))
        .filter(DecisionSnapshot.created_at >= cutoff)
        .subquery()
    )
    snapshots = (
        db.query(DecisionSnapshot)
        .join(
            ranked_snapshot_ids,
            ranked_snapshot_ids.c.snapshot_id == DecisionSnapshot.id,
        )
        .filter(ranked_snapshot_ids.c.strategy_rank <= 2000)
        .order_by(DecisionSnapshot.created_at.desc(), DecisionSnapshot.id.desc())
        .all()
    )
    plans = (
        db.query(TradePlan)
        .filter(TradePlan.strategy_id.in_(strategy_ids))
        .filter(TradePlan.created_at >= cutoff)
        .all()
    )
    risk_count_rows = (
        db.query(
            RiskDecision.strategy_id,
            RiskDecision.strategy_version,
            func.count(RiskDecision.id),
        )
        .filter(RiskDecision.strategy_id.in_(strategy_ids))
        .filter(RiskDecision.created_at >= cutoff)
        .group_by(RiskDecision.strategy_id, RiskDecision.strategy_version)
        .all()
    )
    paper_trades = production_paper_trade_records(
        db.query(PaperTrade)
        .filter(PaperTrade.strategy_id.in_(strategy_ids))
        .filter(PaperTrade.created_at >= cutoff)
        .order_by(PaperTrade.created_at.asc(), PaperTrade.id.asc())
        .all()
    )
    strategy_paper_trades = (
        db.query(StrategyShadowTrade)
        .filter(StrategyShadowTrade.strategy_id.in_(strategy_ids))
        .order_by(StrategyShadowTrade.created_at.asc(), StrategyShadowTrade.id.asc())
        .all()
    )

    return {
        "snapshots": _group_strategy_rows(snapshots),
        "plans": _group_strategy_rows(plans),
        "risk_counts": {
            (strategy_id, strategy_version): int(count)
            for strategy_id, strategy_version, count in risk_count_rows
        },
        "paper_trades": _group_strategy_rows(paper_trades),
        "strategy_paper_trades": _group_strategy_rows(strategy_paper_trades),
    }


def _group_strategy_rows(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row.strategy_id, row.strategy_version)].append(row)
    return dict(grouped)


def _latest_candidates(snapshots, plans, trades, shadow_trades, limit):
    latest_by_symbol = {}
    for row in snapshots:
        if row.symbol not in latest_by_symbol:
            latest_by_symbol[row.symbol] = row

    plan_by_snapshot = {
        plan.strategy_decision_snapshot_id: plan
        for plan in plans
        if plan.strategy_decision_snapshot_id is not None
    }
    trade_by_snapshot = {
        trade.strategy_decision_snapshot_id: trade
        for trade in trades
        if trade.strategy_decision_snapshot_id is not None
    }
    shadow_by_snapshot = {
        trade.strategy_decision_snapshot_id: trade
        for trade in shadow_trades
        if trade.strategy_decision_snapshot_id is not None
    }
    open_plan_by_signal = {
        _strategy_signal_key(
            plan.symbol,
            plan.side,
            plan.entry_timeframe,
        ): plan
        for plan in plans
        if plan.status == "OPEN"
    }
    open_trade_by_signal = {
        _strategy_signal_key(
            trade.symbol,
            trade.side,
            trade.entry_timeframe,
        ): trade
        for trade in trades
        if trade.status == "OPEN"
    }
    open_shadow_by_signal = {
        _strategy_signal_key(
            trade.symbol,
            trade.side,
            trade.entry_timeframe,
        ): trade
        for trade in shadow_trades
        if trade.status == "OPEN"
    }
    records = []
    for row in list(latest_by_symbol.values())[:limit]:
        payload = _json(row.snapshot_json)
        context = payload.get("context") or {}
        participation = context.get("market_participation") or {}
        signal_key = _strategy_signal_key(
            row.symbol,
            context.get("side"),
            row.timeframe,
        )
        # An unchanged eligible scan produces a new decision snapshot while
        # intentionally reusing the existing plan/position. Prefer exact
        # lineage, then fall back only to the same coin, side and timeframe so
        # the UI reflects the real lifecycle without linking an opposite setup.
        plan = plan_by_snapshot.get(row.id) or open_plan_by_signal.get(signal_key)
        trade = trade_by_snapshot.get(row.id) or open_trade_by_signal.get(signal_key)
        shadow_trade = shadow_by_snapshot.get(row.id) or open_shadow_by_signal.get(
            signal_key
        )
        lifecycle = "SIGNAL_BLOCKED"
        if trade is not None:
            lifecycle = "POSITION_OPEN" if trade.status == "OPEN" else "POSITION_CLOSED"
        elif plan is not None:
            lifecycle = "PLAN_OPEN" if plan.status == "OPEN" else "PLAN_CLOSED"
        elif str(row.decision).upper() == "ELIGIBLE":
            lifecycle = "ELIGIBLE_NOT_SELECTED"
        shadow_lifecycle = "SHADOW_NOT_OPENED"
        if shadow_trade is not None:
            shadow_lifecycle = (
                "SHADOW_OPEN"
                if shadow_trade.status == "OPEN"
                else "SHADOW_CLOSED"
            )
        records.append(
            {
                "decision_snapshot_id": row.id,
                "symbol": row.symbol,
                "timeframe": row.timeframe,
                "side": context.get("side"),
                "score": context.get("selected_score"),
                "confidence": row.confidence,
                "decision": row.decision,
                "lifecycle": lifecycle,
                "blocked_reasons": context.get("blocked_reasons") or [],
                "regime_route": context.get("regime_route"),
                "execution_profile": context.get("execution_profile"),
                "entry_location": context.get("entry_location") or {},
                "route_conditions": context.get("route_conditions") or [],
                "stop_model": context.get("stop_model"),
                "market_participation": {
                    "status": participation.get("status"),
                    "direction": participation.get("direction"),
                    "score": participation.get("score"),
                    "reason": participation.get("reason"),
                },
                "trade_plan_id": getattr(plan, "id", None),
                "paper_trade_id": getattr(trade, "id", None),
                "shadow_trade_id": getattr(shadow_trade, "id", None),
                "shadow_lifecycle": shadow_lifecycle,
                "strategy_paper_trade_id": getattr(shadow_trade, "id", None),
                "strategy_paper_lifecycle": shadow_lifecycle.replace(
                    "SHADOW", "STRATEGY_PAPER"
                ),
                "effective_timestamp": row.effective_timestamp,
                "created_at": row.created_at,
            }
        )
    return records


def _strategy_signal_key(symbol, side, timeframe):
    return (
        str(symbol or "").upper(),
        str(side or "").upper(),
        str(timeframe or "").lower(),
    )


def _strategy_performance(trades):
    open_trades = [item for item in trades if item.status == "OPEN"]
    closed = [item for item in trades if item.status == "CLOSED"]
    wins = [item for item in closed if item.result == "WIN"]
    losses = [item for item in closed if item.result == "LOSS"]
    net_pnl_inr = round(
        sum(float(item.realized_pnl_inr or 0) for item in closed),
        2,
    )
    gross_pnl_percent = round(
        sum(float(item.gross_pnl_percent or 0) for item in closed),
        4,
    )
    net_trade_pnl_percent = round(
        sum(float(item.pnl_percent or 0) for item in closed),
        4,
    )
    fees_percent = round(
        sum(float(item.fees_percent or 0) for item in closed),
        4,
    )
    funding_percent = round(
        sum(float(item.funding_cost_percent or 0) for item in closed),
        4,
    )
    return {
        "total_trades": len(trades),
        "open_trades": len(open_trades),
        "closed_trades": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "long_trades": sum(1 for item in trades if item.side == "LONG"),
        "short_trades": sum(1 for item in trades if item.side == "SHORT"),
        "win_rate": round(len(wins) / len(closed) * 100, 2) if closed else 0.0,
        "net_pnl_inr": net_pnl_inr,
        "account_return_percent": round(net_pnl_inr / PAPER_CAPITAL_INR * 100, 4),
        "gross_trade_pnl_percent": gross_pnl_percent,
        "net_trade_pnl_percent": net_trade_pnl_percent,
        "fees_percent": fees_percent,
        "funding_cost_percent": funding_percent,
        "max_drawdown_percent": _max_drawdown_percent(closed),
        "profit_factor": _profit_factor(closed),
        "expectancy_inr": round(net_pnl_inr / len(closed), 2) if closed else 0.0,
    }


def _strategy_paper_trade_payload(trade):
    return {
        "id": trade.id,
        "symbol": trade.symbol,
        "side": trade.side,
        "entry_timeframe": trade.entry_timeframe,
        "entry_price": trade.entry_price,
        "stop_loss": trade.stop_loss,
        "target1": trade.target1,
        "target2": trade.target2,
        "status": trade.status,
        "exit_price": trade.exit_price,
        "exit_reason": trade.exit_reason,
        "result": trade.result,
        "pnl_percent": trade.pnl_percent,
        "realized_pnl_inr": trade.realized_pnl_inr,
        "fees_percent": trade.fees_percent,
        "funding_cost_percent": trade.funding_cost_percent,
        "opened_at": trade.opened_at,
        "closed_at": trade.closed_at,
    }


def _profit_factor(closed):
    gains = sum(max(float(item.realized_pnl_inr or 0), 0) for item in closed)
    losses = abs(sum(min(float(item.realized_pnl_inr or 0), 0) for item in closed))
    if losses == 0:
        return None if gains == 0 else 999.0
    return round(gains / losses, 4)


def _forward_test_readiness(
    performance,
    minimum_closed_trades=30,
    minimum_win_rate=55.0,
    minimum_profit_factor=1.30,
):
    closed = int(performance.get("closed_trades") or 0)
    win_rate = float(performance.get("win_rate") or 0)
    profit_factor = performance.get("profit_factor")
    normalized_profit_factor = (
        float(profit_factor) if profit_factor is not None else 0.0
    )
    expectancy_inr = float(performance.get("expectancy_inr") or 0)
    sample_passed = closed >= minimum_closed_trades
    gates = {
        "sample_size": sample_passed,
        "win_rate": win_rate >= minimum_win_rate,
        "profit_factor": normalized_profit_factor >= minimum_profit_factor,
        "cost_adjusted_expectancy": expectancy_inr > 0,
    }
    promotion_candidate = sample_passed and all(gates.values())
    if not sample_passed:
        status = "COLLECTING"
    elif promotion_candidate:
        status = "PROMOTION_CANDIDATE"
    else:
        status = "EVIDENCE_COMPLETE_FAILED"
    return {
        "status": status,
        "closed_trades": closed,
        "minimum_closed_trades": minimum_closed_trades,
        "remaining_trades": max(0, minimum_closed_trades - closed),
        "minimum_win_rate": minimum_win_rate,
        "minimum_profit_factor": minimum_profit_factor,
        "requires_positive_cost_adjusted_expectancy": True,
        "gates": gates,
        "promotion_candidate": promotion_candidate,
        "authorizes_live_execution": False,
    }


def _shadow_comparison(records):
    ranked = sorted(
        records,
        key=lambda item: (
            float((item.get("shadow_performance") or {}).get("profit_factor") or 0),
            float((item.get("shadow_performance") or {}).get("expectancy_inr") or 0),
            float((item.get("shadow_performance") or {}).get("net_pnl_inr") or 0),
            float((item.get("shadow_performance") or {}).get("win_rate") or 0),
            -float(
                (item.get("shadow_performance") or {}).get(
                    "max_drawdown_percent"
                )
                or 0
            ),
            int((item.get("shadow_performance") or {}).get("closed_trades") or 0),
        ),
        reverse=True,
    )
    evidence_complete = [
        item
        for item in ranked
        if (item.get("forward_test_readiness") or {}).get("status")
        in {"PROMOTION_CANDIDATE", "EVIDENCE_COMPLETE_FAILED"}
    ]
    promotion_candidates = [
        item
        for item in ranked
        if (item.get("forward_test_readiness") or {}).get("promotion_candidate")
    ]
    evidence_ready = len(evidence_complete) == len(records)
    return {
        "status": "EVIDENCE_READY" if evidence_ready else "COLLECTING",
        "execution_book": "STRATEGY_PAPER",
        "minimum_closed_trades_per_strategy": 30,
        "minimum_win_rate": 55.0,
        "minimum_profit_factor": 1.30,
        "requires_positive_cost_adjusted_expectancy": True,
        "research_leader_strategy_id": (
            promotion_candidates[0]["id"]
            if evidence_ready and promotion_candidates
            else None
        ),
        "authorizes_live_execution": False,
        "ranking_method": (
            "profit_factor_then_expectancy_then_net_pnl_then_win_rate_then_drawdown"
        ),
        "ranking": [item["id"] for item in ranked],
    }


def _max_drawdown_percent(closed_trades):
    equity = PAPER_CAPITAL_INR
    peak = equity
    maximum = 0.0
    ordered = sorted(
        closed_trades,
        key=lambda item: (item.closed_at or item.created_at, item.id),
    )
    for trade in ordered:
        equity += float(trade.realized_pnl_inr or 0)
        peak = max(peak, equity)
        drawdown = ((peak - equity) / peak * 100) if peak else 0.0
        maximum = max(maximum, drawdown)
    return round(maximum, 4)


def _json(value):
    try:
        return json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
