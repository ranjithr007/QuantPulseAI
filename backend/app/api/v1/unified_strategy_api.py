"""Safe configuration validation for the Unified Composite strategy."""

from fastapi import APIRouter, Query

from app.contracts.unified_strategy import UnifiedCompositeProfile
from app.database.sqlserver import SessionLocal
from app.intelligence.contradiction_engine import build_contradiction_report


router = APIRouter(prefix="/unified-strategy", tags=["Unified Strategy"])


@router.post("/validate")
def validate_profile(profile: UnifiedCompositeProfile):
    """Validate and normalize a per-coin profile without executing anything."""

    return {
        "status": "VALID",
        "execution": "PAPER_ONLY",
        "orders_created": 0,
        "profile": profile.model_dump(by_alias=True),
    }


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
