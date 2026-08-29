import json

from app.regimes.rules import REGIME_DEFINITIONS
from app.regimes.rules import detect_regime


HYSTERESIS_MARGIN = 7
MIN_TRANSITION_CONFIDENCE = 62
MIN_CANDIDATE_DWELL_CYCLES = 3


def analyze_market(
    feature,
    previous_regime=None,
    *,
    regime_detector=None,
    transition_policy=None,
):
    regime_detector = regime_detector or detect_regime
    transition_policy = transition_policy or _transition_decision
    candidate = regime_detector(feature)
    previous = _previous_state(previous_regime)
    candidate_dwell_cycles = _next_candidate_dwell_cycles(candidate, previous)
    if previous is not None:
        previous = {
            **previous,
            "current_candidate_dwell_cycles": candidate_dwell_cycles,
        }
    transition = transition_policy(candidate, previous)
    selected = candidate

    if transition["decision"] == "HELD_PREVIOUS":
        selected = {
            "regime": previous["regime"],
            "confidence": previous["confidence"],
            "strategy": REGIME_DEFINITIONS[previous["regime"]]["strategy"],
            "bias": REGIME_DEFINITIONS[previous["regime"]]["bias"],
            "direction": REGIME_DEFINITIONS[previous["regime"]]["direction"],
            "risk_mode": REGIME_DEFINITIONS[previous["regime"]]["risk_mode"],
            "reason": "Previous regime held by hysteresis",
        }

    dwell_cycles = _next_dwell_cycles(selected["regime"], previous)
    audit = {
        "engine_version": "v3_regime_13_v2",
        "candidate_regime": candidate["regime"],
        "candidate_dwell_cycles": candidate_dwell_cycles,
        "selected_regime": selected["regime"],
        "previous_regime": previous["regime"] if previous else None,
        "previous_confidence": previous["confidence"] if previous else None,
        "transition_decision": transition["decision"],
        "transition_confidence": transition["confidence"],
        "dwell_cycles": dwell_cycles,
        "hysteresis_margin": HYSTERESIS_MARGIN,
        "min_transition_confidence": MIN_TRANSITION_CONFIDENCE,
        "min_candidate_dwell_cycles": MIN_CANDIDATE_DWELL_CYCLES,
        "transition_policy": getattr(
            transition_policy,
            "__name__",
            str(transition_policy),
        ),
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
        "direction": selected["direction"],
        "risk_mode": selected["risk_mode"],
        "dwell_cycles": dwell_cycles,
        "transition_decision": transition["decision"],
        "transition_confidence": transition["confidence"],
        "audit": audit,
        "reason": json.dumps(audit, sort_keys=True),
    }


def regime_catalog():
    contract = build_regime_contract()
    return {
        "count": contract["count"],
        "regimes": contract["regimes"],
        "hysteresis": contract["thresholds"],
    }


def build_regime_contract():
    regimes = [
        {
            "regime": regime,
            "strategy": definition["strategy"],
            "bias": definition["bias"],
            "direction": definition["direction"],
            "risk_mode": definition["risk_mode"],
        }
        for regime, definition in REGIME_DEFINITIONS.items()
    ]
    return {
        "source": "v3_regime_contract",
        "version": "v3_regime_13_v2",
        "count": len(regimes),
        "regimes": regimes,
        "thresholds": {
            "hysteresis_margin": HYSTERESIS_MARGIN,
            "min_transition_confidence": MIN_TRANSITION_CONFIDENCE,
            "min_candidate_dwell_cycles": MIN_CANDIDATE_DWELL_CYCLES,
        },
        "taxonomy": [item["regime"] for item in regimes],
        "notes": [
            "13-regime taxonomy is governed here",
            "Thresholds are shared across the regime API and engine",
        ],
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
        if (
            int(previous.get("current_candidate_dwell_cycles") or 1)
            >= MIN_CANDIDATE_DWELL_CYCLES
        ):
            return {
                "decision": "CONFIRMED_PERSISTENT_TRANSITION",
                "confidence": candidate["confidence"],
            }
        return {
            "decision": "HELD_PREVIOUS",
            "confidence": max(0, confidence_edge),
        }

    return {
        "decision": "CONFIRMED_TRANSITION",
        "confidence": candidate["confidence"],
    }


def direction_aware_transition_research(candidate, previous):
    """Research-only policy allowing confident Bull/Bear direction reversals."""
    baseline = _transition_decision(candidate, previous)
    if not previous or candidate["regime"] == previous["regime"]:
        return baseline
    if candidate["confidence"] < MIN_TRANSITION_CONFIDENCE:
        return baseline

    candidate_direction = REGIME_DEFINITIONS[candidate["regime"]]["direction"]
    previous_direction = REGIME_DEFINITIONS[previous["regime"]]["direction"]
    if {candidate_direction, previous_direction} == {"BULLISH", "BEARISH"}:
        return {
            "decision": "CONFIRMED_DIRECTION_REVERSAL_RESEARCH",
            "confidence": candidate["confidence"],
        }
    return baseline


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
        "candidate_regime": audit.get("candidate_regime"),
        "candidate_dwell_cycles": int(audit.get("candidate_dwell_cycles") or 0),
    }


def _next_dwell_cycles(selected_regime, previous):
    if previous and previous["regime"] == selected_regime:
        return previous["dwell_cycles"] + 1

    return 1


def _next_candidate_dwell_cycles(candidate, previous):
    if previous and previous.get("candidate_regime") == candidate["regime"]:
        return int(previous.get("candidate_dwell_cycles") or 0) + 1
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
