"""Safe configuration validation and paper activity for the Unified Composite strategy."""

from datetime import datetime
import hashlib
import json

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.contracts.unified_strategy import UnifiedCompositeProfile
from app.database.sqlserver import SessionLocal
from app.intelligence.contradiction_engine import build_contradiction_report
from app.database.models.paper_trade import PaperTrade
from app.paper_trading.entry_price_service import get_current_paper_entry_mark
from app.paper_trading.inr_sizing import PAPER_CAPITAL_INR
from app.repositories.paper_trade_repository import PaperTradeRepository
from app.repositories.paper_wallet_ledger_repository import PaperWalletLedgerRepository
from app.paper_trading.exit_policy import PAPER_EXIT_MONITOR_TIMEFRAME


router = APIRouter(prefix="/unified-strategy", tags=["Unified Strategy"])


class UnifiedPaperExecutionRequest(BaseModel):
    """Explicit user action for one paper position; live execution is impossible."""

    profile: UnifiedCompositeProfile
    symbol: str
    side: str = Field(pattern="^(LONG|SHORT)$")
    timeframe: str = Field(default="1h", pattern="^(1h|2h|4h|1d)$")
    confidence: float | None = Field(default=None, ge=0, le=100)
    entry_price: float | None = Field(default=None, gt=0)
    validation_id: str | None = Field(default=None, max_length=120)


def _profile_validation_id(profile: UnifiedCompositeProfile) -> str:
    payload = json.dumps(profile.model_dump(by_alias=True), sort_keys=True, separators=(",", ":"))
    return "UPV-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12].upper()


@router.post("/validate")
def validate_profile(profile: UnifiedCompositeProfile):
    """Validate and normalize a per-coin profile without executing anything."""

    return {
        "status": "VALID",
        "execution": "PAPER_ONLY",
        "orders_created": 0,
        "validation_id": _profile_validation_id(profile),
        "profile": profile.model_dump(by_alias=True),
    }


@router.get("/activity")
def unified_paper_activity(limit: int = Query(default=20, ge=1, le=100)):
    """Return the persisted Unified paper trades for the strategy page."""

    db = SessionLocal()
    try:
        rows = (
            db.query(PaperTrade)
            .filter(PaperTrade.strategy_id == "UNIFIED_COMPOSITE")
            .order_by(PaperTrade.opened_at.desc(), PaperTrade.id.desc())
            .limit(limit)
            .all()
        )
        trades = []
        for trade in rows:
            evidence = {}
            try:
                evidence = json.loads(trade.execution_evidence_json or "{}")
            except (TypeError, ValueError):
                pass
            trades.append({
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
                "realized_pnl_inr": trade.realized_pnl_inr,
                "pnl_percent": trade.pnl_percent,
                "opened_at": trade.opened_at,
                "validation_id": evidence.get("validation_id"),
                "validation_status": evidence.get("validation_status", "NOT_RECORDED"),
            })
        return {"strategy_id": "UNIFIED_COMPOSITE", "trades": trades}
    finally:
        db.close()


@router.post("/evaluate/{symbol}")
def evaluate_profile(
    symbol: str,
    profile: UnifiedCompositeProfile,
    timeframe: str = Query(default="1h", pattern="^(1h|2h|4h|1d)$"),
):
    """Evaluate a profile against stored engine evidence without creating orders."""

    symbol = symbol.upper()
    if symbol not in {item.upper() for item in profile.execution.allowed_symbols}:
        return {
            "status": "WAIT",
            "reason": "Symbol is not in the profile allowlist",
            "symbol": symbol,
            "timeframe": timeframe,
            "orders_created": 0,
        }

    db = SessionLocal()
    try:
        report = build_contradiction_report(db, symbol, timeframe)
        confidence = float(report.get("confidence") or 0)
        allowed = bool(report.get("trade_allowed"))
        reasons = list(report.get("reasons") or [])
        if confidence < profile.entry.minimum_confidence:
            allowed = False
            reasons.append("Composite confidence is below the profile minimum")
        decision = report.get("bias") if allowed else "WAIT"
        return {
            "status": decision,
            "symbol": symbol,
            "timeframe": timeframe,
            "confidence": confidence,
            "reasons": reasons,
            "engine_policy": profile.engines.model_dump(by_alias=True),
            "risk": profile.risk.model_dump(),
            "orders_created": 0,
            "source_report": report,
        }
    finally:
        db.close()


@router.post("/paper-trade")
def execute_unified_paper_trade(request: UnifiedPaperExecutionRequest):
    """Open exactly one governed Unified Composite paper position.

    This endpoint is deliberately an explicit action. It never connects to an
    exchange and derives exits and sizing from the submitted profile controls.
    """
    profile = request.profile
    symbol = request.symbol.upper()
    allowed = {item.upper() for item in profile.execution.allowed_symbols}
    if symbol not in allowed:
        raise HTTPException(400, "Symbol is not in the profile allowlist")
    if profile.mode == "LIVE_AUTO" or not profile.execution.paper_only:
        raise HTTPException(400, "Unified execution is paper-only")
    current_validation_id = _profile_validation_id(profile)
    if request.validation_id and request.validation_id != current_validation_id:
        raise HTTPException(400, "Profile changed after validation; validate the current profile before executing")

    mark = get_current_paper_entry_mark(symbol) if request.entry_price is None else None
    entry = float(request.entry_price or (mark or {}).get("mark_price") or 0)
    if entry <= 0:
        raise HTTPException(409, "A fresh paper entry mark is unavailable")

    confidence = float(request.confidence if request.confidence is not None else profile.entry.minimum_confidence)
    if confidence < profile.entry.minimum_confidence:
        raise HTTPException(400, "Confidence is below the profile minimum")
    direction = 1 if request.side == "LONG" else -1
    stop_percent = max(0.10, min(5.0, 0.75 * profile.risk.atr_multiplier))
    stop = entry * (1 - direction * stop_percent / 100)
    risk_distance = abs(entry - stop)
    target1 = entry + direction * risk_distance * profile.exit.target1_reward_to_risk
    target2 = entry + direction * risk_distance * profile.exit.target2_reward_to_risk
    risk_percent = float(profile.risk.risk_per_trade_percent)
    notional = min(PAPER_CAPITAL_INR * 0.85, PAPER_CAPITAL_INR * risk_percent / (stop_percent / 100))
    leverage = min(float(profile.risk.maximum_leverage), 1.0)
    margin = notional / leverage

    db = SessionLocal()
    try:
        repo = PaperTradeRepository()
        repo.acquire_account_execution_lock(db)
        if repo.has_open_trade(db, symbol):
            raise HTTPException(409, "An open paper trade already exists for this symbol")
        open_count = len(repo.get_open_trades(db))
        if open_count >= profile.risk.maximum_open_positions:
            raise HTTPException(409, "Maximum open paper positions reached")
        validation_id = request.validation_id or "NOT_VALIDATED"
        trade = PaperTrade(
            symbol=symbol, side=request.side, entry_price=entry,
            planned_entry_price=entry, stop_loss=stop, initial_stop_loss=stop,
            target1=target1, target2=target2, position_size=notional,
            risk_reward=profile.exit.target2_reward_to_risk,
            risk_percent=risk_percent, confidence=confidence, mode=profile.mode,
            entry_timeframe=request.timeframe, timeframe_stack=request.timeframe,
            strategy_id="UNIFIED_COMPOSITE", strategy_version="unified_composite_v1",
            exit_policy="UNIFIED_PROFILE", target1_fraction=profile.exit.target1_close_fraction,
            remaining_position_fraction=1.0, max_hold_hours=profile.exit.maximum_hold_hours,
            exit_monitor_timeframe=PAPER_EXIT_MONITOR_TIMEFRAME,
            paper_capital_at_entry_inr=PAPER_CAPITAL_INR,
            allocation_percent=notional / PAPER_CAPITAL_INR * 100,
            position_notional_inr=notional, leverage=leverage, margin_used_inr=margin,
            partial_realized_pnl_inr=0.0, fee_bps=7.5, status="OPEN",
            opened_at=datetime.utcnow(), created_at=datetime.utcnow(),
            execution_evidence_json=json.dumps({
                "source": "UNIFIED_COMPOSITE_MANUAL_BUTTON",
                "paper_only": True,
                "validation_id": validation_id,
                "validation_status": "VALIDATED" if request.validation_id else "NOT_VALIDATED",
            }, separators=(",", ":")),
        )
        db.add(trade)
        db.flush()
        PaperWalletLedgerRepository().append_event(
            db, event_key=f"paper_trade:{trade.id}:ENTRY", paper_trade_id=trade.id,
            symbol=symbol, event_type="ENTRY", position_notional_inr=notional,
            margin_inr=margin, position_fraction=1.0, created_at=trade.opened_at,
        )
        db.commit()
        db.refresh(trade)
        return {"status": "EXECUTED", "execution": "PAPER_ONLY", "orders_created": 1,
                "trade": {"id": trade.id, "symbol": symbol, "side": request.side,
                           "entry_price": entry, "stop_loss": stop, "target1": target1,
                           "target2": target2, "position_notional_inr": notional,
                           "margin_used_inr": margin, "mode": profile.mode,
                           "validation_id": validation_id}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(503, f"Paper trade could not be created: {exc}") from exc
    finally:
        db.close()
