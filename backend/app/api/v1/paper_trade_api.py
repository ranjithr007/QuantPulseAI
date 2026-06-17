from fastapi import APIRouter, Query

from app.database.sqlserver import SessionLocal
from app.paper_trading.paper_trade_performance import paper_trade_performance
from app.repositories.paper_trade_repository import PaperTradeRepository
from app.repositories.risk_repository import RiskRepository
from app.repositories.trade_plan_repository import TradePlanRepository
from app.utils.freshness import freshness_status


router = APIRouter(prefix="/paper-trade", tags=["Paper Trade"])


@router.get("/performance")
def get_paper_trade_performance(symbol: str | None = Query(default=None)):
    db = SessionLocal()

    try:
        normalized_symbol = symbol.upper() if symbol else None
        repo = PaperTradeRepository()
        trades = repo.all_trades(db, symbol=normalized_symbol)

        return {
            "source": "paper_trade_performance",
            "symbol_filter": normalized_symbol,
            "performance": paper_trade_performance(trades),
        }

    finally:
        db.close()


@router.get("/trades")
def get_paper_trades(
    status: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
):
    db = SessionLocal()

    try:
        normalized_status = status.upper() if status else None
        normalized_symbol = symbol.upper() if symbol else None
        repo = PaperTradeRepository()
        records = [
            _paper_trade_payload(trade)
            for trade in repo.list_trades(
                db,
                status=normalized_status,
                symbol=normalized_symbol,
                limit=limit,
            )
        ]

        return {
            "source": "paper_trades",
            "status_filter": normalized_status,
            "symbol_filter": normalized_symbol,
            "count": len(records),
            "summary": _summarize_paper_trades(records),
            "records": records,
        }

    finally:
        db.close()


@router.get("/candidates")
def get_paper_trade_candidates(
    symbol: str | None = Query(default=None),
    stale_after_seconds: int = Query(default=900, ge=1),
):
    db = SessionLocal()

    try:
        normalized_symbol, records = build_paper_trade_candidates(
            db,
            symbol,
            stale_after_seconds,
        )
        eligible = [
            item
            for item in records
            if item["eligible"]
        ]

        return {
            "source": "paper_trade_candidates",
            "symbol_filter": normalized_symbol,
            "count": len(records),
            "eligible_count": len(eligible),
            "blocked_count": len(records) - len(eligible),
            "records": records,
        }

    finally:
        db.close()


@router.post("/execute-candidates")
def execute_paper_trade_candidates(
    symbol: str | None = Query(default=None),
    stale_after_seconds: int = Query(default=900, ge=1),
):
    return execute_paper_trade_candidates_for_symbol(
        symbol=symbol,
        stale_after_seconds=stale_after_seconds,
    )


def execute_paper_trade_candidates_for_symbol(symbol=None, stale_after_seconds=900):
    db = SessionLocal()

    try:
        normalized_symbol, records = build_paper_trade_candidates(
            db,
            symbol,
            stale_after_seconds,
        )
        repo = PaperTradeRepository()
        executed = []
        skipped = []

        for candidate in records:
            if not candidate["eligible"]:
                skipped.append(
                    {
                        "symbol": candidate["symbol"],
                        "side": candidate["side"],
                        "action": "skipped_not_eligible",
                        "blocked_reasons": candidate["blocked_reasons"],
                    }
                )
                continue

            if repo.has_open_trade(db, candidate["symbol"], candidate["side"]):
                skipped.append(
                    {
                        "symbol": candidate["symbol"],
                        "side": candidate["side"],
                        "action": "skipped_existing_open_paper_trade",
                    }
                )
                continue

            paper_trade = repo.save_candidate(db, candidate)
            executed.append(_paper_trade_payload(paper_trade))

        return {
            "source": "paper_trade_execution_simulator",
            "symbol_filter": normalized_symbol,
            "candidate_count": len(records),
            "executed_count": len(executed),
            "skipped_count": len(skipped),
            "executed": executed,
            "skipped": skipped,
        }

    finally:
        db.close()


def build_paper_trade_candidates(db, symbol=None, stale_after_seconds=900):
    trade_repo = TradePlanRepository()
    risk_repo = RiskRepository()
    trades = trade_repo.get_open_trades(db)

    if symbol:
        normalized_symbol = symbol.upper()
        trades = [
            trade
            for trade in trades
            if trade.symbol == normalized_symbol
        ]
    else:
        normalized_symbol = None

    records = [
        _paper_trade_candidate(
            trade,
            risk_repo.latest_for_symbol(db, trade.symbol),
            stale_after_seconds,
        )
        for trade in trades
    ]

    return normalized_symbol, records


def _paper_trade_payload(paper_trade):
    return {
        "id": paper_trade.id,
        "trade_plan_id": paper_trade.trade_plan_id,
        "risk_decision_id": paper_trade.risk_decision_id,
        "symbol": paper_trade.symbol,
        "side": paper_trade.side,
        "entry_price": paper_trade.entry_price,
        "stop_loss": paper_trade.stop_loss,
        "target1": paper_trade.target1,
        "target2": paper_trade.target2,
        "position_size": paper_trade.position_size,
        "risk_reward": paper_trade.risk_reward,
        "risk_percent": paper_trade.risk_percent,
        "confidence": paper_trade.confidence,
        "status": paper_trade.status,
        "exit_price": paper_trade.exit_price,
        "result": paper_trade.result,
        "pnl_percent": paper_trade.pnl_percent,
        "opened_at": paper_trade.opened_at,
        "closed_at": paper_trade.closed_at,
        "created_at": paper_trade.created_at,
    }


def _summarize_paper_trades(records):
    return {
        "open": sum(1 for item in records if item["status"] == "OPEN"),
        "closed": sum(1 for item in records if item["status"] == "CLOSED"),
        "wins": sum(1 for item in records if item["result"] == "WIN"),
        "losses": sum(1 for item in records if item["result"] == "LOSS"),
    }


def _paper_trade_candidate(trade, risk, stale_after_seconds):
    risk_payload = _risk_decision_payload(risk, stale_after_seconds)
    blocked_reasons = _paper_trade_blocked_reasons(trade, risk, risk_payload)

    return {
        "symbol": trade.symbol,
        "side": trade.side,
        "eligible": not blocked_reasons,
        "blocked_reasons": blocked_reasons,
        "trade_plan": _trade_plan_payload(trade),
        "risk_decision": risk_payload,
    }


def _trade_plan_payload(trade):
    return {
        "id": trade.id,
        "status": trade.status,
        "entry_price": trade.entry_price,
        "stop_loss": trade.stop_loss,
        "target1": trade.target1,
        "target2": trade.target2,
        "target3": trade.target3,
        "risk_reward": trade.risk_reward,
        "confidence": trade.confidence,
        "created_at": trade.created_at,
    }


def _risk_decision_payload(risk, stale_after_seconds):
    if risk is None:
        return {
            "decision": "NO_RISK_DECISION",
            "freshness": freshness_status(None, stale_after_seconds),
        }

    return {
        "id": risk.id,
        "signal": risk.signal,
        "decision": risk.decision,
        "entry_price": risk.entry_price,
        "stop_loss": risk.stop_loss,
        "target1": risk.target1,
        "target2": risk.target2,
        "risk_reward": risk.risk_reward,
        "position_size": risk.position_size,
        "risk_percent": risk.risk_percent,
        "confidence": risk.confidence,
        "created_at": risk.created_at,
        "freshness": freshness_status(risk.created_at, stale_after_seconds),
    }


def _paper_trade_blocked_reasons(trade, risk, risk_payload):
    reasons = []

    if risk is None:
        return ["No risk decision found for trade plan"]

    if risk.decision != "APPROVE":
        reasons.append(f"Risk decision is not APPROVE: {risk.decision}")

    if risk_payload["freshness"]["is_stale"]:
        reasons.append("Risk decision is stale")

    if risk.signal != trade.side:
        reasons.append("Risk signal does not match trade side")

    if not _same_price(risk.entry_price, trade.entry_price):
        reasons.append("Risk entry does not match trade entry")

    if not _same_price(risk.stop_loss, trade.stop_loss):
        reasons.append("Risk stop_loss does not match trade stop_loss")

    if not _same_price(risk.target1, trade.target1):
        reasons.append("Risk target1 does not match trade target1")

    if trade.created_at and risk.created_at and risk.created_at < trade.created_at:
        reasons.append("Risk decision is older than trade plan")

    return reasons


def _same_price(left, right):
    if left is None or right is None:
        return False

    return abs(float(left) - float(right)) <= 0.00000001
