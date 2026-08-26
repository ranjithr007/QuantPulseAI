import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Query

from app.database.models.paper_trade import PaperTrade
from app.database.models.point_in_time_snapshots import DecisionSnapshot
from app.database.models.risk_decision import RiskDecision
from app.database.models.trade_plan import TradePlan
from app.database.sqlserver import SessionLocal
from app.paper_trading.evidence_scope import production_paper_trade_records
from app.paper_trading.inr_sizing import PAPER_CAPITAL_INR
from app.strategies.registry import STRATEGY_REGISTRY
from app.strategies.registry import CORE_FUSION_DECISION_VERSION
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
        records = [
            _strategy_record(db, definition, cutoff, candidate_limit)
            for definition in definitions
        ]
        return {
            "source": "strategy_performance_v1",
            "status": "READY",
            "execution_scope": "PAPER_ONLY",
            "since_days": since_days,
            "one_active_trade_per_symbol": True,
            "strategy_count": len(records),
            "records": records,
        }
    finally:
        db.close()


def _strategy_record(db, definition, cutoff, candidate_limit):
    strategy_id = definition["id"]
    strategy_version = definition["version"]
    snapshots = (
        db.query(DecisionSnapshot)
        .filter(DecisionSnapshot.strategy_id == strategy_id)
        .filter(DecisionSnapshot.strategy_version == strategy_version)
        .filter(DecisionSnapshot.decision_version == CORE_FUSION_DECISION_VERSION)
        .filter(DecisionSnapshot.created_at >= cutoff)
        .order_by(DecisionSnapshot.created_at.desc(), DecisionSnapshot.id.desc())
        .limit(2000)
        .all()
    )
    plans = (
        db.query(TradePlan)
        .filter(TradePlan.strategy_id == strategy_id)
        .filter(TradePlan.strategy_version == strategy_version)
        .filter(TradePlan.created_at >= cutoff)
        .all()
    )
    risks = (
        db.query(RiskDecision)
        .filter(RiskDecision.strategy_id == strategy_id)
        .filter(RiskDecision.strategy_version == strategy_version)
        .filter(RiskDecision.created_at >= cutoff)
        .all()
    )
    trades = production_paper_trade_records(
        db.query(PaperTrade)
        .filter(PaperTrade.strategy_id == strategy_id)
        .filter(PaperTrade.strategy_version == strategy_version)
        .filter(PaperTrade.created_at >= cutoff)
        .order_by(PaperTrade.created_at.asc(), PaperTrade.id.asc())
        .all()
    )
    candidates = _latest_candidates(snapshots, plans, trades, candidate_limit)
    return {
        **definition,
        "coverage": {
            "decision_snapshots": len(snapshots),
            "trade_plans": len(plans),
            "risk_decisions": len(risks),
            "paper_trades": len(trades),
            "eligible_signals": sum(
                1 for item in snapshots if str(item.decision).upper() == "ELIGIBLE"
            ),
            "blocked_signals": sum(
                1 for item in snapshots if str(item.decision).upper() == "BLOCKED"
            ),
        },
        "performance": _strategy_performance(trades),
        "candidates": candidates,
    }


def _latest_candidates(snapshots, plans, trades, limit):
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
    records = []
    for row in list(latest_by_symbol.values())[:limit]:
        payload = _json(row.snapshot_json)
        context = payload.get("context") or {}
        participation = context.get("market_participation") or {}
        plan = plan_by_snapshot.get(row.id)
        trade = trade_by_snapshot.get(row.id)
        lifecycle = "SIGNAL_BLOCKED"
        if trade is not None:
            lifecycle = "POSITION_OPEN" if trade.status == "OPEN" else "POSITION_CLOSED"
        elif plan is not None:
            lifecycle = "PLAN_OPEN" if plan.status == "OPEN" else "PLAN_CLOSED"
        elif str(row.decision).upper() == "ELIGIBLE":
            lifecycle = "ELIGIBLE_NOT_SELECTED"
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
                "market_participation": {
                    "status": participation.get("status"),
                    "direction": participation.get("direction"),
                    "score": participation.get("score"),
                    "reason": participation.get("reason"),
                },
                "trade_plan_id": getattr(plan, "id", None),
                "paper_trade_id": getattr(trade, "id", None),
                "effective_timestamp": row.effective_timestamp,
                "created_at": row.created_at,
            }
        )
    return records


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
