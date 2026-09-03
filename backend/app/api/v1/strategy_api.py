import json
from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Query
from sqlalchemy import and_, case, func, or_

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
    include_ledger: bool = True,
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
        strategy_data = _load_strategy_data(
            db,
            definitions,
            cutoff,
            include_ledger=include_ledger,
        )
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
            "ledger_included": include_ledger,
            "strategy_count": len(records),
            "comparison": _shadow_comparison(records),
            "records": records,
        }
    finally:
        db.close()


@router.get("/ledger")
def get_strategy_ledger(
    strategy_id: str | None = Query(default=None),
    history_limit: int = Query(default=20, ge=1, le=100),
):
    """Return lifetime Strategy Paper wallet and history without blocking summary."""

    normalized = str(strategy_id or "").upper() or None
    if normalized and normalized not in STRATEGY_REGISTRY:
        return {
            "source": "strategy_ledger_v1",
            "status": "NOT_FOUND",
            "strategy_id": normalized,
            "records": [],
        }

    definitions = (
        [strategy_definition(normalized)]
        if normalized
        else list(STRATEGY_REGISTRY.values())
    )
    db = SessionLocal()
    try:
        strategy_data = _load_strategy_ledger_data(
            db,
            definitions,
            history_limit=history_limit,
        )
        return {
            "source": "strategy_ledger_v1",
            "status": "READY",
            "execution_scope": "PAPER_ONLY",
            "strategy_count": len(definitions),
            "records": [
                _strategy_ledger_record_from_data(definition, strategy_data)
                for definition in definitions
            ],
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
    snapshot_counts = strategy_data["snapshot_counts"].get(key, {})
    candidates = _latest_candidates(
        snapshots,
        plans,
        trades,
        strategy_book_trades,
        candidate_limit,
    )
    official_performance = strategy_data["official_performance"].get(
        key, _empty_strategy_performance()
    )
    shadow_performance = strategy_data["strategy_paper_performance"].get(
        key, _empty_strategy_performance()
    )
    ledger_loaded = bool(strategy_data.get("ledger_loaded"))
    strategy_book_performance = strategy_data.get(
        "strategy_paper_lifetime_performance", {}
    ).get(key, _empty_strategy_performance())
    strategy_book_history = strategy_data.get("strategy_paper_history", {}).get(
        key, []
    )
    return {
        **definition,
        "coverage": {
            "decision_snapshots": snapshot_counts.get("total", 0),
            "trade_plans": strategy_data["plan_counts"].get(key, 0),
            "risk_decisions": strategy_data["risk_counts"].get(key, 0),
            "paper_trades": official_performance["total_trades"],
            "shadow_trades": shadow_performance["total_trades"],
            "strategy_paper_trades": shadow_performance["total_trades"],
            "strategy_paper_lifetime_trades": strategy_book_performance[
                "total_trades"
            ],
            "eligible_signals": snapshot_counts.get("eligible", 0),
            "blocked_signals": snapshot_counts.get("blocked", 0),
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
            for item in strategy_book_history
        ],
        "ledger_loaded": ledger_loaded,
        "official_performance": official_performance,
        "forward_test_readiness": _forward_test_readiness(shadow_performance),
        "candidates": candidates,
    }


def _load_strategy_data(db, definitions, cutoff, *, include_ledger=True):
    """Load aggregate coverage plus only the rows needed by visible candidates."""

    strategy_ids = [definition["id"] for definition in definitions]
    decision_versions = [
        definition["decision_version"] for definition in definitions
    ]
    if not strategy_ids:
        return {
            "snapshots": {},
            "plans": {},
            "snapshot_counts": {},
            "plan_counts": {},
            "risk_counts": {},
            "paper_trades": {},
            "strategy_paper_trades": {},
            "official_performance": {},
            "strategy_paper_performance": {},
            "strategy_paper_lifetime_performance": {},
            "strategy_paper_history": {},
            "ledger_loaded": include_ledger,
        }

    snapshot_count_rows = (
        db.query(
            DecisionSnapshot.strategy_id,
            DecisionSnapshot.strategy_version,
            func.count(DecisionSnapshot.id),
            func.sum(
                case(
                    (func.upper(DecisionSnapshot.decision) == "ELIGIBLE", 1),
                    else_=0,
                )
            ),
            func.sum(
                case(
                    (func.upper(DecisionSnapshot.decision) == "BLOCKED", 1),
                    else_=0,
                )
            ),
        )
        .filter(DecisionSnapshot.strategy_id.in_(strategy_ids))
        .filter(DecisionSnapshot.decision_version.in_(decision_versions))
        .filter(DecisionSnapshot.created_at >= cutoff)
        .group_by(DecisionSnapshot.strategy_id, DecisionSnapshot.strategy_version)
        .all()
    )
    latest_snapshot_ids = (
        db.query(
            func.max(DecisionSnapshot.id).label("snapshot_id"),
        )
        .filter(DecisionSnapshot.strategy_id.in_(strategy_ids))
        .filter(DecisionSnapshot.decision_version.in_(decision_versions))
        .filter(DecisionSnapshot.created_at >= cutoff)
        .group_by(
            DecisionSnapshot.strategy_id,
            DecisionSnapshot.strategy_version,
            DecisionSnapshot.decision_version,
            DecisionSnapshot.symbol,
        )
        .subquery()
    )
    snapshots = (
        db.query(DecisionSnapshot)
        .join(
            latest_snapshot_ids,
            latest_snapshot_ids.c.snapshot_id == DecisionSnapshot.id,
        )
        .order_by(DecisionSnapshot.created_at.desc(), DecisionSnapshot.id.desc())
        .all()
    )
    snapshot_ids = [item.id for item in snapshots]
    plans = (
        db.query(TradePlan)
        .filter(TradePlan.strategy_decision_snapshot_id.in_(snapshot_ids))
        .all()
        if snapshot_ids
        else []
    )
    plan_count_rows = (
        db.query(
            TradePlan.strategy_id,
            TradePlan.strategy_version,
            func.count(TradePlan.id),
        )
        .filter(TradePlan.strategy_id.in_(strategy_ids))
        .filter(TradePlan.created_at >= cutoff)
        .group_by(TradePlan.strategy_id, TradePlan.strategy_version)
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
    candidate_scope = [
        model.strategy_decision_snapshot_id.in_(snapshot_ids)
        for model in (PaperTrade, StrategyShadowTrade)
    ]
    paper_trades = production_paper_trade_records(
        db.query(PaperTrade)
        .filter(PaperTrade.strategy_id.in_(strategy_ids))
        .filter(or_(candidate_scope[0], PaperTrade.status == "OPEN"))
        .order_by(PaperTrade.created_at.asc(), PaperTrade.id.asc())
        .all()
    )
    strategy_paper_trades = (
        db.query(StrategyShadowTrade)
        .filter(StrategyShadowTrade.strategy_id.in_(strategy_ids))
        .filter(
            or_(candidate_scope[1], StrategyShadowTrade.status == "OPEN")
        )
        .order_by(StrategyShadowTrade.created_at.asc(), StrategyShadowTrade.id.asc())
        .all()
    )

    official_performance = _load_strategy_performance(
        db,
        PaperTrade,
        strategy_ids,
        cutoff=cutoff,
        exclude_qa_symbols=True,
    )
    strategy_paper_performance = _load_strategy_performance(
        db,
        StrategyShadowTrade,
        strategy_ids,
        cutoff=cutoff,
    )
    if include_ledger:
        ledger_data = _load_strategy_ledger_data(
            db,
            definitions,
            history_limit=20,
        )
        strategy_paper_lifetime_performance = ledger_data[
            "strategy_paper_lifetime_performance"
        ]
        strategy_paper_history = ledger_data["strategy_paper_history"]
    else:
        strategy_paper_lifetime_performance = {}
        strategy_paper_history = {}

    return {
        "snapshots": _group_strategy_rows(snapshots),
        "plans": _group_strategy_rows(plans),
        "snapshot_counts": {
            (strategy_id, strategy_version): {
                "total": int(total or 0),
                "eligible": int(eligible or 0),
                "blocked": int(blocked or 0),
            }
            for strategy_id, strategy_version, total, eligible, blocked in snapshot_count_rows
        },
        "plan_counts": {
            (strategy_id, strategy_version): int(count)
            for strategy_id, strategy_version, count in plan_count_rows
        },
        "risk_counts": {
            (strategy_id, strategy_version): int(count)
            for strategy_id, strategy_version, count in risk_count_rows
        },
        "paper_trades": _group_strategy_rows(paper_trades),
        "strategy_paper_trades": _group_strategy_rows(strategy_paper_trades),
        "official_performance": official_performance,
        "strategy_paper_performance": strategy_paper_performance,
        "strategy_paper_lifetime_performance": (
            strategy_paper_lifetime_performance
        ),
        "strategy_paper_history": strategy_paper_history,
        "ledger_loaded": include_ledger,
    }


def _load_strategy_ledger_data(db, definitions, *, history_limit):
    strategy_ids = [definition["id"] for definition in definitions]
    if not strategy_ids:
        return {
            "strategy_paper_lifetime_performance": {},
            "strategy_paper_history": {},
        }
    return {
        "strategy_paper_lifetime_performance": _load_strategy_performance(
            db,
            StrategyShadowTrade,
            strategy_ids,
        ),
        "strategy_paper_history": _load_recent_strategy_rows(
            db,
            StrategyShadowTrade,
            strategy_ids,
            per_strategy_limit=history_limit,
        ),
    }


def _strategy_ledger_record_from_data(definition, strategy_data):
    key = (definition["id"], definition["version"])
    performance = strategy_data["strategy_paper_lifetime_performance"].get(
        key, _empty_strategy_performance()
    )
    history = strategy_data["strategy_paper_history"].get(key, [])
    return {
        "id": definition["id"],
        "version": definition["version"],
        "ledger_loaded": True,
        "strategy_paper_lifetime_performance": performance,
        "strategy_paper_wallet": {
            "initial_capital_inr": PAPER_CAPITAL_INR,
            "realized_pnl_inr": performance["net_pnl_inr"],
            "wallet_balance_inr": round(
                PAPER_CAPITAL_INR + performance["net_pnl_inr"],
                2,
            ),
            "open_position_count": performance["open_trades"],
        },
        "strategy_paper_history": [
            _strategy_paper_trade_payload(item) for item in history
        ],
    }


def _load_strategy_performance(
    db,
    model,
    strategy_ids,
    *,
    cutoff=None,
    exclude_qa_symbols=False,
):
    """Aggregate strategy results in SQL instead of hydrating the full ledger."""

    closed = func.upper(model.status) == "CLOSED"
    opened = func.upper(model.status) == "OPEN"
    realized = func.coalesce(model.realized_pnl_inr, 0.0)
    query = db.query(
        model.strategy_id,
        model.strategy_version,
        func.count(model.id).label("total_trades"),
        func.sum(case((opened, 1), else_=0)).label("open_trades"),
        func.sum(case((closed, 1), else_=0)).label("closed_trades"),
        func.sum(
            case((and_(closed, func.upper(model.result) == "WIN"), 1), else_=0)
        ).label("wins"),
        func.sum(
            case((and_(closed, func.upper(model.result) == "LOSS"), 1), else_=0)
        ).label("losses"),
        func.sum(case((func.upper(model.side) == "LONG", 1), else_=0)).label(
            "long_trades"
        ),
        func.sum(case((func.upper(model.side) == "SHORT", 1), else_=0)).label(
            "short_trades"
        ),
        func.sum(case((closed, realized), else_=0.0)).label("net_pnl_inr"),
        func.sum(
            case((closed, func.coalesce(model.gross_pnl_percent, 0.0)), else_=0.0)
        ).label("gross_trade_pnl_percent"),
        func.sum(
            case((closed, func.coalesce(model.pnl_percent, 0.0)), else_=0.0)
        ).label("net_trade_pnl_percent"),
        func.sum(
            case((closed, func.coalesce(model.fees_percent, 0.0)), else_=0.0)
        ).label("fees_percent"),
        func.sum(
            case(
                (closed, func.coalesce(model.funding_cost_percent, 0.0)),
                else_=0.0,
            )
        ).label("funding_cost_percent"),
        func.sum(case((and_(closed, realized > 0), realized), else_=0.0)).label(
            "gross_gains"
        ),
        func.sum(case((and_(closed, realized < 0), realized), else_=0.0)).label(
            "gross_losses"
        ),
    ).filter(model.strategy_id.in_(strategy_ids))
    if cutoff is not None:
        query = query.filter(model.created_at >= cutoff)
    if exclude_qa_symbols:
        query = query.filter(func.upper(model.symbol).notlike("QA%"))
    rows = query.group_by(model.strategy_id, model.strategy_version).all()
    drawdowns = _load_strategy_drawdowns(
        db,
        model,
        strategy_ids,
        cutoff=cutoff,
        exclude_qa_symbols=exclude_qa_symbols,
    )
    return {
        (row.strategy_id, row.strategy_version): _performance_from_aggregate(
            row,
            drawdowns.get((row.strategy_id, row.strategy_version), 0.0),
        )
        for row in rows
    }


def _load_strategy_drawdowns(
    db,
    model,
    strategy_ids,
    *,
    cutoff=None,
    exclude_qa_symbols=False,
):
    """Calculate maximum drawdown with SQL windows, returning one row per book."""

    order_time = func.coalesce(model.closed_at, model.created_at)
    realized = func.coalesce(model.realized_pnl_inr, 0.0)
    partition = (model.strategy_id, model.strategy_version)
    equity_query = db.query(
        model.strategy_id.label("strategy_id"),
        model.strategy_version.label("strategy_version"),
        model.id.label("trade_id"),
        order_time.label("order_time"),
        (
            PAPER_CAPITAL_INR
            + func.sum(realized).over(
                partition_by=partition,
                order_by=(order_time, model.id),
                rows=(None, 0),
            )
        ).label("equity"),
    ).filter(model.strategy_id.in_(strategy_ids))
    equity_query = equity_query.filter(func.upper(model.status) == "CLOSED")
    if cutoff is not None:
        equity_query = equity_query.filter(model.created_at >= cutoff)
    if exclude_qa_symbols:
        equity_query = equity_query.filter(func.upper(model.symbol).notlike("QA%"))
    equity = equity_query.subquery()
    with_peak = db.query(
        equity.c.strategy_id,
        equity.c.strategy_version,
        equity.c.equity,
        func.max(equity.c.equity)
        .over(
            partition_by=(equity.c.strategy_id, equity.c.strategy_version),
            order_by=(equity.c.order_time, equity.c.trade_id),
            rows=(None, 0),
        )
        .label("peak"),
    ).subquery()
    running_peak = case(
        (with_peak.c.peak < PAPER_CAPITAL_INR, PAPER_CAPITAL_INR),
        else_=with_peak.c.peak,
    )
    drawdown = case(
        (
            running_peak > 0,
            (running_peak - with_peak.c.equity) / running_peak * 100.0,
        ),
        else_=0.0,
    )
    rows = (
        db.query(
            with_peak.c.strategy_id,
            with_peak.c.strategy_version,
            func.max(drawdown).label("max_drawdown_percent"),
        )
        .group_by(with_peak.c.strategy_id, with_peak.c.strategy_version)
        .all()
    )
    return {
        (row.strategy_id, row.strategy_version): round(
            float(row.max_drawdown_percent or 0.0), 4
        )
        for row in rows
    }


def _load_recent_strategy_rows(db, model, strategy_ids, *, per_strategy_limit):
    ranked = db.query(
        model.id.label("row_id"),
        func.row_number()
        .over(
            partition_by=(model.strategy_id, model.strategy_version),
            order_by=(model.created_at.desc(), model.id.desc()),
        )
        .label("row_number"),
    ).filter(model.strategy_id.in_(strategy_ids)).subquery()
    rows = (
        db.query(model)
        .join(ranked, ranked.c.row_id == model.id)
        .filter(ranked.c.row_number <= per_strategy_limit)
        .order_by(
            model.strategy_id.asc(),
            model.strategy_version.asc(),
            model.created_at.desc(),
            model.id.desc(),
        )
        .all()
    )
    return _group_strategy_rows(rows)


def _performance_from_aggregate(row, max_drawdown_percent):
    total = int(row.total_trades or 0)
    closed = int(row.closed_trades or 0)
    wins = int(row.wins or 0)
    net_pnl_inr = round(float(row.net_pnl_inr or 0.0), 2)
    gains = float(row.gross_gains or 0.0)
    losses = abs(float(row.gross_losses or 0.0))
    profit_factor = (
        round(gains / losses, 4)
        if losses
        else (999.0 if gains else None)
    )
    return {
        "total_trades": total,
        "open_trades": int(row.open_trades or 0),
        "closed_trades": closed,
        "wins": wins,
        "losses": int(row.losses or 0),
        "long_trades": int(row.long_trades or 0),
        "short_trades": int(row.short_trades or 0),
        "win_rate": round(wins / closed * 100, 2) if closed else 0.0,
        "net_pnl_inr": net_pnl_inr,
        "account_return_percent": round(net_pnl_inr / PAPER_CAPITAL_INR * 100, 4),
        "gross_trade_pnl_percent": round(
            float(row.gross_trade_pnl_percent or 0.0), 4
        ),
        "net_trade_pnl_percent": round(
            float(row.net_trade_pnl_percent or 0.0), 4
        ),
        "fees_percent": round(float(row.fees_percent or 0.0), 4),
        "funding_cost_percent": round(float(row.funding_cost_percent or 0.0), 4),
        "max_drawdown_percent": round(float(max_drawdown_percent or 0.0), 4),
        "profit_factor": profit_factor,
        "expectancy_inr": round(net_pnl_inr / closed, 2) if closed else 0.0,
    }


def _empty_strategy_performance():
    return _strategy_performance([])


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
