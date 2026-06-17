from fastapi import APIRouter, Query

from app.api.v1.paper_trade_api import build_paper_trade_candidates
from app.api.v1.signals_api import get_signal_watchlist
from app.database.models.risk_decision import RiskDecision
from app.database.sqlserver import SessionLocal
from app.paper_trading.paper_trade_performance import paper_trade_performance
from app.repositories.paper_trade_repository import PaperTradeRepository
from app.repositories.trade_plan_repository import TradePlanRepository


router = APIRouter(prefix="/pipeline", tags=["Pipeline"])


@router.get("/status")
def get_pipeline_status(
    mode: str | None = Query(default="intraday"),
    stale_after_seconds: int = Query(default=900, ge=1),
):
    watchlist = get_signal_watchlist(
        mode=mode,
        lower=None,
        middle=None,
        higher=None,
        status=None,
        side=None,
        failed_max=None,
        stale_after_seconds=stale_after_seconds,
    )
    db = SessionLocal()

    try:
        trade_repo = TradePlanRepository()
        paper_repo = PaperTradeRepository()
        open_trade_plans = trade_repo.get_open_trades(db)
        risk_count = db.query(RiskDecision).count()
        latest_risk = (
            db.query(RiskDecision)
            .order_by(RiskDecision.created_at.desc())
            .first()
        )
        _, candidates = build_paper_trade_candidates(
            db,
            stale_after_seconds=stale_after_seconds,
        )
        eligible_candidates = [
            item
            for item in candidates
            if item["eligible"]
        ]
        paper_trades = paper_repo.all_trades(db)
        open_paper_trades = [
            trade
            for trade in paper_trades
            if trade.status == "OPEN"
        ]
        closed_paper_trades = [
            trade
            for trade in paper_trades
            if trade.status == "CLOSED"
        ]
        stages = {
            "watchlist": _watchlist_stage(watchlist),
            "trade_plans": _trade_plan_stage(open_trade_plans),
            "risk": _risk_stage(risk_count, latest_risk),
            "paper_candidates": _paper_candidate_stage(
                candidates,
                eligible_candidates,
            ),
            "paper_trades": _paper_trade_stage(
                open_paper_trades,
                closed_paper_trades,
            ),
            "performance": paper_trade_performance(paper_trades),
        }

        return {
            "source": "pipeline_status",
            "mode": mode,
            "timeframes": watchlist["timeframes"],
            "status": _pipeline_status(stages),
            "blockers": _pipeline_blockers(stages),
            "stages": stages,
        }

    finally:
        db.close()


def _watchlist_stage(watchlist):
    summary = watchlist["summary"]

    return {
        "count": watchlist["count"],
        "ready": summary["ready"],
        "wait": summary["wait"],
        "long": summary["long"],
        "short": summary["short"],
        "has_ready": summary["ready"] > 0,
    }


def _trade_plan_stage(open_trade_plans):
    return {
        "open_count": len(open_trade_plans),
        "symbols": [trade.symbol for trade in open_trade_plans],
        "has_open": bool(open_trade_plans),
    }


def _risk_stage(risk_count, latest_risk):
    return {
        "count": risk_count,
        "has_decisions": risk_count > 0,
        "latest": _latest_risk_payload(latest_risk),
    }


def _latest_risk_payload(risk):
    if risk is None:
        return None

    return {
        "symbol": risk.symbol,
        "signal": risk.signal,
        "decision": risk.decision,
        "created_at": risk.created_at,
    }


def _paper_candidate_stage(candidates, eligible_candidates):
    return {
        "count": len(candidates),
        "eligible_count": len(eligible_candidates),
        "blocked_count": len(candidates) - len(eligible_candidates),
        "has_eligible": bool(eligible_candidates),
    }


def _paper_trade_stage(open_paper_trades, closed_paper_trades):
    return {
        "open_count": len(open_paper_trades),
        "closed_count": len(closed_paper_trades),
        "has_open": bool(open_paper_trades),
    }


def _pipeline_status(stages):
    blockers = _pipeline_blockers(stages)

    return "READY" if not blockers else "WAIT"


def _pipeline_blockers(stages):
    blockers = []

    if not stages["watchlist"]["has_ready"]:
        blockers.append("No READY watchlist setups")

    if not stages["trade_plans"]["has_open"]:
        blockers.append("No OPEN trade plans")

    if not stages["risk"]["has_decisions"]:
        blockers.append("No risk decisions")

    if not stages["paper_candidates"]["has_eligible"]:
        blockers.append("No eligible paper-trade candidates")

    if not stages["paper_trades"]["has_open"]:
        blockers.append("No OPEN paper trades")

    return blockers
