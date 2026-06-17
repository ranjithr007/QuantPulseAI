import json

from app.regimes.rules import REGIME_DEFINITIONS
from app.regimes.rules import detect_regime


HYSTERESIS_MARGIN = 7
MIN_TRANSITION_CONFIDENCE = 62


def analyze_market(feature, previous_regime=None):
    candidate = detect_regime(feature)
    previous = _previous_state(previous_regime)
    transition = _transition_decision(candidate, previous)
    selected = candidate

    if transition["decision"] == "HELD_PREVIOUS":
        selected = {
            "regime": previous["regime"],
            "confidence": previous["confidence"],
            "strategy": REGIME_DEFINITIONS[previous["regime"]]["strategy"],
            "bias": REGIME_DEFINITIONS[previous["regime"]]["bias"],
            "risk_mode": REGIME_DEFINITIONS[previous["regime"]]["risk_mode"],
            "reason": "Previous regime held by hysteresis",
        }

    dwell_cycles = _next_dwell_cycles(selected["regime"], previous)
    audit = {
        "engine_version": "v3_regime_13_v1",
        "candidate_regime": candidate["regime"],
        "selected_regime": selected["regime"],
        "previous_regime": previous["regime"] if previous else None,
        "previous_confidence": previous["confidence"] if previous else None,
        "transition_decision": transition["decision"],
        "transition_confidence": transition["confidence"],
        "dwell_cycles": dwell_cycles,
        "hysteresis_margin": HYSTERESIS_MARGIN,
        "min_transition_confidence": MIN_TRANSITION_CONFIDENCE,
        "candidate_reason": candidate["reason"],
        "selected_reason": selected["reason"],
        "feature_snapshot": _feature_snapshot(feature),
    }

    return {
        "symbol": feature.Symbol,
        "timeframe": feature.Timeframe,
        "regime": selected["regime"],
        "confidence": selected["confidence"],
        "strategy": selected["strategy"],
        "bias": selected["bias"],
        "risk_mode": selected["risk_mode"],
        "dwell_cycles": dwell_cycles,
        "transition_decision": transition["decision"],
        "transition_confidence": transition["confidence"],
        "audit": audit,
        "reason": json.dumps(audit, sort_keys=True),
    }


def regime_catalog():
    return {
        "count": len(REGIME_DEFINITIONS),
        "regimes": [
            {
                "regime": regime,
                "strategy": definition["strategy"],
                "bias": definition["bias"],
                "risk_mode": definition["risk_mode"],
            }
            for regime, definition in REGIME_DEFINITIONS.items()
        ],
        "hysteresis": {
            "margin": HYSTERESIS_MARGIN,
            "min_transition_confidence": MIN_TRANSITION_CONFIDENCE,
        },
    }


def parse_regime_audit(reason):
    if not reason:
        return None

    try:
        return json.loads(reason)
    except (TypeError, ValueError):
        return {"legacy_reason": reason}


def _transition_decision(candidate, previous):
    if not previous:
        return {
            "decision": "INITIAL",
            "confidence": candidate["confidence"],
        }

    if candidate["regime"] == previous["regime"]:
        return {
            "decision": "SAME",
            "confidence": candidate["confidence"],
        }

    confidence_edge = candidate["confidence"] - previous["confidence"]

    if candidate["confidence"] < MIN_TRANSITION_CONFIDENCE:
        return {
            "decision": "HELD_PREVIOUS",
            "confidence": max(0, candidate["confidence"]),
        }

    if confidence_edge < HYSTERESIS_MARGIN:
        return {
            "decision": "HELD_PREVIOUS",
            "confidence": max(0, confidence_edge),
        }

    return {
        "decision": "CONFIRMED_TRANSITION",
        "confidence": candidate["confidence"],
    }


def _previous_state(previous_regime):
    if not previous_regime:
        return None

    regime = getattr(previous_regime, "Regime", None)

    if regime not in REGIME_DEFINITIONS:
        return None

    audit = parse_regime_audit(getattr(previous_regime, "Reason", None)) or {}

    return {
        "regime": regime,
        "confidence": float(getattr(previous_regime, "Confidence", 0) or 0),
        "dwell_cycles": int(audit.get("dwell_cycles") or 1),
    }


def _next_dwell_cycles(selected_regime, previous):
    if previous and previous["regime"] == selected_regime:
        return previous["dwell_cycles"] + 1

    return 1


def _feature_snapshot(feature):
    return {
        "trend_score": getattr(feature, "TrendScore", None),
        "momentum_score": getattr(feature, "MomentumScore", None),
        "volatility_score": getattr(feature, "VolatilityScore", None),
        "liquidity_score": getattr(feature, "LiquidityScore", None),
        "final_score": getattr(feature, "FinalScore", None),
        "trend": getattr(feature, "Trend", None),
        "signal": getattr(feature, "Signal", None),
    }
