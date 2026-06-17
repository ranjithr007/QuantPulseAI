from fastapi import APIRouter, Query

from app.repositories.risk_repository import RiskRepository
from app.utils.freshness import freshness_status
from app.utils.signal_validation import validate_trade_plan_direction

router = APIRouter(prefix="/risk", tags=["Risk"])


repo = RiskRepository()


@router.get("/{symbol}")
def get_risk(symbol: str, stale_after_seconds: int = Query(default=900, ge=1)):

    risk = repo.latest(symbol)

    if not risk:

        return {
            "symbol": symbol,
            "source": "risk_decisions",
            "decision": "NO_RISK_DECISION",
            "freshness": freshness_status(None, stale_after_seconds),
            "message": "No persisted risk decision found for symbol",
        }

    validation = validate_trade_plan_direction(
        risk.signal,
        risk.entry_price,
        risk.target1,
    )
    freshness = freshness_status(risk.created_at, stale_after_seconds)
    is_usable = validation["is_valid"] and not freshness["is_stale"]

    return {
        "symbol": risk.symbol,
        "source": "risk_decisions",
        "status": _risk_status(freshness, validation),
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
        "freshness": freshness,
        "is_valid_trade_plan": validation["is_valid"],
        "is_usable": is_usable,
        "ignored_reasons": _ignored_reasons(freshness, validation),
        "validation_errors": validation["errors"],
    }


def _risk_status(freshness, validation):
    if not freshness["is_stale"] and validation["is_valid"]:
        return "current_valid"

    if freshness["is_stale"] and not validation["is_valid"]:
        return "historical_stale_invalid"

    if freshness["is_stale"]:
        return "historical_stale"

    return "current_invalid"


def _ignored_reasons(freshness, validation):
    reasons = []

    if freshness["is_stale"]:
        reasons.append("Risk decision is stale")

    reasons.extend(validation["errors"])

    return reasons
