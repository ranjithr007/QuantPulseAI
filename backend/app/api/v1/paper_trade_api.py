from fastapi import APIRouter, Query
from sqlalchemy.exc import SQLAlchemyError

from app.api.v1.derivatives_api import build_derivatives_payload
from app.database.sqlserver import SessionLocal
from app.paper_trading.fill_model import build_fill_profile
from app.paper_trading.measurement import MeasurementGates
from app.paper_trading.measurement import attach_regime_outcome_context
from app.paper_trading.measurement import attach_scenario_context
from app.paper_trading.measurement import build_measurement_report
from app.paper_trading.paper_trade_performance import paper_trade_performance
from app.paper_trading.validation_policy import build_architecture_paper_gate
from app.risk.risk_engine import RiskEngine
from app.repositories.paper_trade_repository import PaperTradeRepository
from app.repositories.risk_repository import RiskRepository
from app.repositories.trade_plan_repository import TradePlanRepository
from app.utils.freshness import freshness_status


router = APIRouter(prefix="/paper-trade", tags=["Paper Trade"])
risk_engine = RiskEngine()


def build_paper_trade_bundle(db, symbol=None, open_limit=120, closed_limit=200):
    normalized_symbol = symbol.upper() if symbol else None
    repo = PaperTradeRepository()

    trades = repo.all_trades(db, symbol=normalized_symbol)
    open_trades = [
        _paper_trade_payload(trade)
        for trade in repo.list_trades(db, status="OPEN", symbol=normalized_symbol, limit=open_limit)
    ]
    closed_trades = [
        _paper_trade_payload(trade)
        for trade in repo.list_trades(db, status="CLOSED", symbol=normalized_symbol, limit=closed_limit)
    ]
    total_pnl_percent = round(sum(item.get("pnl_percent", 0) or 0 for item in closed_trades), 2)
    wins = sum(1 for item in closed_trades if (item.get("pnl_percent") or 0) > 0)
    losses = sum(1 for item in closed_trades if (item.get("pnl_percent") or 0) < 0)
    closed_count = len(closed_trades)

    return {
        "source": "paper_trade_bundle",
        "symbol_filter": normalized_symbol,
        "marketContext": _market_context_payload(normalized_symbol),
        "performance": {
            **paper_trade_performance(trades),
            "total_trades": len(trades),
            "open_trades": len(open_trades),
            "closed_trades": closed_count,
            "wins": wins,
            "losses": losses,
            "win_rate": round((wins / closed_count) * 100, 2) if closed_count else 0,
            "average_pnl_percent": round(total_pnl_percent / closed_count, 2) if closed_count else 0,
            "total_pnl_percent": total_pnl_percent,
            "closedTrades": closed_trades,
        },
        "summary": _summarize_paper_trades(open_trades + closed_trades),
        "openTrades": {
            "count": len(open_trades),
            "records": open_trades,
        },
        "closedTrades": {
            "count": len(closed_trades),
            "records": closed_trades,
        },
    }


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

    except SQLAlchemyError as exc:
        return _paper_trade_unavailable_payload(
            operation="performance",
            symbol_filter=symbol,
            detail="Paper-trade performance is unavailable because the database is not reachable.",
        )

    finally:
        db.close()


@router.get("/measurement")
def get_paper_trade_measurement(
    symbol: str | None = Query(default=None),
    min_closed_trades: int = Query(default=100, ge=1, le=100000),
    min_observation_days: int = Query(default=90, ge=1, le=3650),
    min_profit_factor: float = Query(default=1.3, gt=0, le=100),
    min_expectancy_percent: float = Query(default=0.0, ge=-100, le=100),
    min_total_return_percent: float = Query(default=0.0, ge=-100, le=100000),
    max_drawdown_percent: float = Query(default=20.0, gt=0, le=100),
    min_cohort_closed_trades: int = Query(default=20, ge=1, le=100000),
):
    db = SessionLocal()

    try:
        normalized_symbol = symbol.upper() if symbol else None
        trades = PaperTradeRepository().all_trades(db, symbol=normalized_symbol)
        attach_scenario_context(db, trades)
        attach_regime_outcome_context(db, trades)
        report = build_measurement_report(
            trades,
            gates=MeasurementGates(
                min_closed_trades=min_closed_trades,
                min_observation_days=min_observation_days,
                min_profit_factor=min_profit_factor,
                min_expectancy_percent=min_expectancy_percent,
                min_total_return_percent=min_total_return_percent,
                max_drawdown_percent=max_drawdown_percent,
                min_cohort_closed_trades=min_cohort_closed_trades,
            ),
        )
        return {
            "source": "extended_paper_trade_measurement",
            "symbol_filter": normalized_symbol,
            "report": report,
            "architecture_gate": build_architecture_paper_gate(report),
        }
    except SQLAlchemyError:
        return _paper_trade_unavailable_payload(
            operation="measurement",
            symbol_filter=symbol,
            detail="Paper-trade measurement is unavailable because the database is not reachable.",
        )
    finally:
        db.close()


@router.get("/bundle")
def get_paper_trade_bundle(symbol: str | None = Query(default=None)):
    db = SessionLocal()

    try:
        return build_paper_trade_bundle(db, symbol=symbol)

    except SQLAlchemyError:
        return _paper_trade_unavailable_payload(
            operation="bundle",
            symbol_filter=symbol,
            detail="Paper-trade bundle is unavailable because the database is not reachable.",
        )

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

    except SQLAlchemyError as exc:
        return _paper_trade_unavailable_payload(
            operation="trades",
            symbol_filter=symbol,
            status_filter=normalized_status,
            detail="Paper-trade list is unavailable because the database is not reachable.",
        )

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

    except SQLAlchemyError as exc:
        return _paper_trade_unavailable_payload(
            operation="candidates",
            symbol_filter=symbol,
            detail="Paper-trade candidates are unavailable because the database is not reachable.",
        )

    finally:
        db.close()


@router.get("/fill-model")
def get_paper_trade_fill_model(
    side: str = Query(...),
    planned_entry_price: float = Query(..., gt=0),
    stop_loss: float | None = Query(default=None),
    target1: float | None = Query(default=None),
    confidence: float = Query(default=50, ge=0, le=100),
    risk_reward: float | None = Query(default=None),
    fee_bps: float = Query(default=4, ge=0, le=1000),
):
    return {
        "source": "paper_trade_fill_model",
        "profile": build_fill_profile(
            side=side,
            planned_entry_price=planned_entry_price,
            stop_loss=stop_loss,
            target1=target1,
            confidence=confidence,
            risk_reward=risk_reward,
            fee_bps=fee_bps,
        ),
    }


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

            trade_plan_id = candidate["trade_plan"]["id"]
            if repo.has_trade_for_plan(db, trade_plan_id):
                skipped.append(
                    {
                        "symbol": candidate["symbol"],
                        "side": candidate["side"],
                        "action": "skipped_existing_paper_trade_for_plan",
                        "trade_plan_id": trade_plan_id,
                    }
                )
                continue

            paper_trade = repo.save_candidate(db, candidate)
            executed.append(
                _paper_trade_payload(
                    paper_trade,
                    fill_profile=candidate.get("fill_profile"),
                )
            )

        return {
            "source": "paper_trade_execution_simulator",
            "symbol_filter": normalized_symbol,
            "candidate_count": len(records),
            "executed_count": len(executed),
            "skipped_count": len(skipped),
            "executed": executed,
            "skipped": skipped,
        }

    except SQLAlchemyError as exc:
        return _paper_trade_execution_unavailable_payload(
            symbol_filter=symbol,
            detail="Paper-trade execution is unavailable because the database is not reachable.",
        )

    finally:
        db.close()


def build_paper_trade_candidates(
    db,
    symbol=None,
    stale_after_seconds=900,
    trades=None,
):
    trade_repo = TradePlanRepository()
    risk_repo = RiskRepository()
    trades = trades if trades is not None else trade_repo.get_open_trades(db)

    if symbol:
        normalized_symbol = symbol.upper()
        trades = [
            trade
            for trade in trades
            if trade.symbol == normalized_symbol
        ]
    else:
        normalized_symbol = None

    latest_risks = risk_repo.latest_for_symbols(
        db,
        [trade.symbol for trade in trades],
    )
    derivative_payloads = {
        trade_symbol: _safe_derivatives_payload(
            db,
            trade_symbol,
            stale_after_seconds=stale_after_seconds,
        )
        for trade_symbol in {trade.symbol for trade in trades}
    }
    records = [
        _paper_trade_candidate(
            trade,
            latest_risks.get(trade.symbol),
            stale_after_seconds,
            derivative_payloads.get(trade.symbol),
        )
        for trade in trades
    ]

    return normalized_symbol, records


def _paper_trade_payload(paper_trade, fill_profile=None):
    payload = {
        "id": paper_trade.id,
        "trade_plan_id": paper_trade.trade_plan_id,
        "risk_decision_id": paper_trade.risk_decision_id,
        "thesis_id": getattr(paper_trade, "thesis_id", None),
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
        "mode": paper_trade.mode,
        "entry_timeframe": paper_trade.entry_timeframe,
        "timeframe_stack": paper_trade.timeframe_stack,
        "regime": paper_trade.regime,
        "fee_bps": paper_trade.fee_bps,
        "fees_percent": paper_trade.fees_percent,
        "gross_pnl_percent": paper_trade.gross_pnl_percent,
        "status": paper_trade.status,
        "exit_price": paper_trade.exit_price,
        "result": paper_trade.result,
        "pnl_percent": paper_trade.pnl_percent,
        "opened_at": paper_trade.opened_at,
        "closed_at": paper_trade.closed_at,
        "created_at": paper_trade.created_at,
        "market_type": "FUTURES",
        "instrument_type": "PERPETUAL",
        "venue": "BINANCE_FUTURES",
    }

    if fill_profile is not None:
        payload["fill_profile"] = fill_profile

    return payload


def _summarize_paper_trades(records):
    return {
        "open": sum(1 for item in records if item["status"] == "OPEN"),
        "closed": sum(1 for item in records if item["status"] == "CLOSED"),
        "wins": sum(1 for item in records if item["result"] == "WIN"),
        "losses": sum(1 for item in records if item["result"] == "LOSS"),
    }


def _paper_trade_candidate(trade, risk, stale_after_seconds, derivatives=None):
    risk_payload = _risk_decision_payload(risk, stale_after_seconds)
    blocked_reasons = _paper_trade_blocked_reasons(trade, risk, risk_payload, derivatives)
    fill_profile = build_fill_profile(
        side=trade.side,
        planned_entry_price=trade.entry_price,
        stop_loss=trade.stop_loss,
        target1=trade.target1,
        confidence=risk_payload.get("confidence", trade.confidence or 50),
        risk_reward=trade.risk_reward,
    )

    return {
        "symbol": trade.symbol,
        "side": trade.side,
        "eligible": not blocked_reasons,
        "blocked_reasons": blocked_reasons,
        "trade_plan": _trade_plan_payload(trade),
        "risk_decision": risk_payload,
        "fill_profile": fill_profile,
        "market_context": _market_context_payload(trade.symbol, derivatives),
    }


def _trade_plan_payload(trade):
    return {
        "id": trade.id,
        "thesis_id": getattr(trade, "thesis_id", None),
        "status": trade.status,
        "entry_price": trade.entry_price,
        "stop_loss": trade.stop_loss,
        "target1": trade.target1,
        "target2": trade.target2,
        "target3": trade.target3,
        "risk_reward": trade.risk_reward,
        "confidence": trade.confidence,
        "mode": getattr(trade, "mode", None),
        "entry_timeframe": getattr(trade, "entry_timeframe", None),
        "timeframe_stack": getattr(trade, "timeframe_stack", None),
        "regime": getattr(trade, "regime", None),
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
        "reason": _risk_reason(risk),
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


def _paper_trade_blocked_reasons(trade, risk, risk_payload, derivatives=None):
    reasons = []

    if risk is None:
        return ["No risk decision found for trade plan"]

    if risk.decision != "APPROVE":
        rejection_reason = _risk_reason(risk)
        if rejection_reason:
            reasons.append(
                f"Risk decision is not APPROVE: {risk.decision} ({rejection_reason})"
            )
        else:
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


def _market_context_payload(symbol=None, derivatives=None):
    availability = (derivatives or {}).get("availability") or {}
    funding_available = bool(availability.get("funding"))
    open_interest_available = bool(availability.get("open_interest"))
    return {
        "symbol": symbol,
        "market_type": "FUTURES",
        "instrument_type": "PERPETUAL",
        "venue": "BINANCE_FUTURES",
        "fundingAvailable": funding_available,
        "openInterestAvailable": open_interest_available,
        "isReady": funding_available and open_interest_available,
    }


def _safe_derivatives_payload(db, symbol, stale_after_seconds):
    try:
        return build_derivatives_payload(
            db,
            symbol,
            stale_after_seconds=stale_after_seconds,
        )
    except SQLAlchemyError:
        db.rollback()
        return {}


def _same_price(left, right):
    if left is None or right is None:
        return False

    return abs(float(left) - float(right)) <= 0.00000001


def _risk_reason(risk):
    stored_reason = getattr(risk, "reason", None)

    if stored_reason:
        return stored_reason

    if str(getattr(risk, "decision", "") or "").upper() != "REJECT":
        return None

    try:
        recomputed = risk_engine.analyze_trade_plan(
            symbol=risk.symbol,
            side=risk.signal,
            entry=risk.entry_price,
            stop_loss=risk.stop_loss,
            target1=risk.target1,
            target2=risk.target2,
            confidence=risk.confidence or 0,
            risk_percent=risk.risk_percent or 1,
        )
    except Exception:
        return None

    return recomputed.get("reason")


def _paper_trade_unavailable_payload(operation, symbol_filter=None, status_filter=None, detail="Paper-trade data is unavailable because the database is not reachable."):
    normalized_symbol = symbol_filter.upper() if symbol_filter else None
    payload = {
        "source": f"paper_trade_{operation}_fallback",
        "database_status": "UNAVAILABLE",
        "message": detail,
    }

    if normalized_symbol is not None:
        payload["symbol_filter"] = normalized_symbol

    if status_filter is not None:
        payload["status_filter"] = status_filter

    if operation == "performance":
        payload["performance"] = {
            "total_trades": 0,
            "open_trades": 0,
            "closed_trades": 0,
            "wins": 0,
            "losses": 0,
            "long_trades": 0,
            "short_trades": 0,
            "win_rate": 0,
            "average_pnl_percent": 0,
            "total_pnl_percent": 0,
        }
    elif operation == "trades":
        payload.update(
            {
                "count": 0,
                "summary": {"open": 0, "closed": 0, "wins": 0, "losses": 0},
                "records": [],
            }
        )
    elif operation == "candidates":
        payload.update(
            {
                "count": 0,
                "eligible_count": 0,
                "blocked_count": 0,
                "records": [],
            }
        )
    elif operation == "bundle":
        payload.update(
            {
                "performance": {
                    "total_trades": 0,
                    "open_trades": 0,
                    "closed_trades": 0,
                    "wins": 0,
                    "losses": 0,
                    "long_trades": 0,
                    "short_trades": 0,
                    "win_rate": 0,
                    "average_pnl_percent": 0,
                    "total_pnl_percent": 0,
                },
                "summary": {"open": 0, "closed": 0, "wins": 0, "losses": 0},
                "openTrades": {"count": 0, "records": []},
                "closedTrades": {"count": 0, "records": []},
            }
        )
    elif operation == "measurement":
        payload["report"] = build_measurement_report([])

    return payload


def _paper_trade_execution_unavailable_payload(symbol_filter=None, detail="Paper-trade execution is unavailable because the database is not reachable."):
    normalized_symbol = symbol_filter.upper() if symbol_filter else None
    payload = {
        "source": "paper_trade_execution_simulator_fallback",
        "database_status": "UNAVAILABLE",
        "message": detail,
        "symbol_filter": normalized_symbol,
        "candidate_count": 0,
        "executed_count": 0,
        "skipped_count": 0,
        "executed": [],
        "skipped": [],
    }
    return payload
