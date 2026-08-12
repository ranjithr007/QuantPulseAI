from app.governance.evidence_policy import FULL_SIZE_ENTRY_CONFIDENCE
from app.governance.evidence_policy import MINIMUM_TIER_RISK_PERCENT


def confidence_sizing_profile(confidence, configured_max_risk_percent):
    """Return the paper-trade risk tier for an already eligible signal."""
    confidence = float(confidence)
    configured_max_risk_percent = float(configured_max_risk_percent)

    if confidence < FULL_SIZE_ENTRY_CONFIDENCE:
        return {
            "position_tier": "MINIMUM",
            "risk_percent": min(
                configured_max_risk_percent,
                MINIMUM_TIER_RISK_PERCENT,
            ),
            "requested_risk_percent": configured_max_risk_percent,
        }

    return {
        "position_tier": "MAXIMUM",
        "risk_percent": configured_max_risk_percent,
        "requested_risk_percent": configured_max_risk_percent,
    }
