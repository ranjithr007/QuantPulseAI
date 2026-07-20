from fastapi import APIRouter, Query

from app.api.v1.paper_trade_api import build_paper_trade_candidates
from app.api.v1.signals_api import build_signal_watchlist_payload
from app.backtesting.walk_forward_validator import PHASE2_OFFICIAL_TIMEFRAMES
from app.database.models.risk_decision import RiskDecision
from app.database.sqlserver import SessionLocal
from app.paper_trading.paper_trade_performance import paper_trade_performance
from app.repositories.paper_trade_repository import PaperTradeRepository
from app.repositories.trade_plan_repository import TradePlanRepository
from app.observability.performance_budget import LatencyBudget
from app.observability.performance_budget import build_stage_latency_report
from app.utils.network_resilience import summarize_network_error


router = APIRouter(prefix="/pipeline", tags=["Pipeline"])

PIPELINE_STAGE_BUDGETS = {
    "watchlist": LatencyBudget(p50_ms=250.0, p95_ms=750.0, p99_ms=1500.0),
    "trade_plans": LatencyBudget(p50_ms=20.0, p95_ms=50.0, p99_ms=100.0),
    "risk": LatencyBudget(p50_ms=20.0, p95_ms=50.0, p99_ms=100.0),
    "paper_candidates": LatencyBudget(p50_ms=250.0, p95_ms=750.0, p99_ms=1500.0),
    "paper_trades": LatencyBudget(p50_ms=20.0, p95_ms=50.0, p99_ms=100.0),
    "performance": LatencyBudget(p50_ms=10.0, p95_ms=25.0, p99_ms=50.0),
}


@router.get("/status")
def get_pipeline_status(
    mode: str | None = Query(default="intraday"),
    stale_after_seconds: int = Query(default=900, ge=1),
):
    db = SessionLocal()

    try:
        watchlist = build_signal_watchlist_payload(
            db,
            mode=mode,
            lower=None,
            middle=None,
            higher=None,
            status=None,
            side=None,
            failed_max=None,
            stale_after_seconds=stale_after_seconds,
        )
        trade_repo = TradePlanRepository()
        paper_repo = PaperTradeRepository()
        open_trade_plans = _official_trade_plans(trade_repo.get_open_trades(db))
        risk_count = db.query(RiskDecision).count()
        latest_risk = (
            db.query(RiskDecision)
            .order_by(RiskDecision.created_at.desc())
            .first()
        )
        _, candidates = build_paper_trade_candidates(
            db,
            stale_after_seconds=stale_after_seconds,
            trades=open_trade_plans,
        )
        eligible_candidates = [
            item
            for item in candidates
            if item["eligible"]
        ]
        paper_trades = _official_paper_trades(paper_repo.all_trades(db))
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
            "paper_evidence_scope": _paper_evidence_scope(),
            "status": _pipeline_status(stages),
            "blockers": _pipeline_blockers(stages),
            "stages": stages,
        }

    except Exception as exc:
        db.rollback()
        return {
            "source": "pipeline_status",
            "mode": mode,
            "timeframes": [],
            "status": "FAILED",
            "blockers": ["Pipeline status unavailable"],
            "stages": {},
            "error": summarize_network_error(exc),
        }

    finally:
        db.close()


@router.get("/performance")
def get_pipeline_performance(
    mode: str | None = Query(default="intraday"),
    stale_after_seconds: int = Query(default=900, ge=1),
    sample_size: int = Query(default=5, ge=1, le=20),
):
    db = SessionLocal()

    try:
        trade_repo = TradePlanRepository()
        paper_repo = PaperTradeRepository()
        open_trade_plans = _official_trade_plans(trade_repo.get_open_trades(db))
        paper_trades = _official_paper_trades(paper_repo.all_trades(db))

        def _watchlist():
            return build_signal_watchlist_payload(
                db,
                mode=mode,
                lower=None,
                middle=None,
                higher=None,
                status=None,
                side=None,
                failed_max=None,
                stale_after_seconds=stale_after_seconds,
            )

        def _trade_plans():
            return open_trade_plans

        def _risk():
            latest_risk = (
                db.query(RiskDecision)
                .order_by(RiskDecision.created_at.desc())
                .first()
            )
            return {
                "count": db.query(RiskDecision).count(),
                "latest": _latest_risk_payload(latest_risk),
            }

        def _paper_candidates():
            return build_paper_trade_candidates(
                db,
                stale_after_seconds=stale_after_seconds,
                trades=open_trade_plans,
            )

        def _paper_trades():
            return paper_trades

        def _performance():
            return paper_trade_performance(paper_trades)

        stage_report = build_stage_latency_report(
            {
                "watchlist": _watchlist,
                "trade_plans": _trade_plans,
                "risk": _risk,
                "paper_candidates": _paper_candidates,
                "paper_trades": _paper_trades,
                "performance": _performance,
            },
            sample_size=sample_size,
            budgets=PIPELINE_STAGE_BUDGETS,
        )

        return {
            "source": "pipeline_performance_budget",
            "mode": mode,
            "stale_after_seconds": stale_after_seconds,
            "sample_size": sample_size,
            "paper_evidence_scope": _paper_evidence_scope(),
            "stages": stage_report["stages"],
            "budget_summary": _budget_summary(stage_report["stages"]),
        }

    except Exception as exc:
        db.rollback()
        return {
            "source": "pipeline_performance_budget",
            "mode": mode,
            "stale_after_seconds": stale_after_seconds,
            "sample_size": sample_size,
            "stages": {},
            "budget_summary": {"stages": 0, "passed": 0, "failed": 0},
            "error": summarize_network_error(exc),
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


def _official_trade_plans(trades):
    return [
        trade
        for trade in (trades or [])
        if str(getattr(trade, "entry_timeframe", "") or "").strip()
        in PHASE2_OFFICIAL_TIMEFRAMES
    ]


def _official_paper_trades(trades):
    return [
        trade
        for trade in (trades or [])
        if str(getattr(trade, "entry_timeframe", "") or "").strip()
        in PHASE2_OFFICIAL_TIMEFRAMES
    ]


def _paper_evidence_scope():
    return {
        "market": "FUTURES",
        "mode": "intraday",
        "entry_timeframes": sorted(PHASE2_OFFICIAL_TIMEFRAMES),
        "excluded_legacy_timeframes": ["5m", "15m"],
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


def _budget_summary(stage_reports):
    total = len(stage_reports)
    passed = sum(1 for item in stage_reports.values() if item["budget_passed"])

    return {
        "stages": total,
        "passed": passed,
        "failed": total - passed,
    }
