from app.utils.freshness import freshness_status


MARKET_PARTICIPATION_MAX_AGE_SECONDS = 75 * 60
MARKET_PARTICIPATION_EXECUTION_THRESHOLD = 40.0


def evaluate_market_participation(payload, side):
    """Return the single market-participation decision used by every entry surface."""
    normalized_side = _normalize_side(side)
    expected_direction = (
        "BULLISH" if normalized_side == "LONG"
        else "BEARISH" if normalized_side == "SHORT"
        else None
    )
    direction = str((payload or {}).get("direction") or "NEUTRAL").upper()
    confidence = _number((payload or {}).get("confidence"))
    score = _number((payload or {}).get("score"), confidence if direction == "BULLISH" else -confidence)
    freshness = freshness_status(
        (payload or {}).get("effective_timestamp"),
        MARKET_PARTICIPATION_MAX_AGE_SECONDS,
    )

    base = {
        "allowed": False,
        "status": "UNAVAILABLE",
        "reason": "Market participation trend is unavailable",
        "side": normalized_side,
        "expected_direction": expected_direction,
        "direction": direction,
        "score": score,
        "confidence": confidence,
        "execution_threshold": MARKET_PARTICIPATION_EXECUTION_THRESHOLD,
        "quality_state": (payload or {}).get("quality_state"),
        "effective_timestamp": (payload or {}).get("effective_timestamp"),
        "freshness": freshness,
    }
    if not payload:
        return base
    if not expected_direction:
        return {
            **base,
            "status": "NO_DIRECTION",
            "reason": "A LONG or SHORT signal is required for market participation confirmation",
        }
    if freshness.get("is_stale"):
        return {
            **base,
            "status": "STALE",
            "reason": "Market participation trend is stale",
        }
    if payload.get("status") != "READY" or payload.get("quality_state") != "OK":
        return {
            **base,
            "status": "DEGRADED",
            "reason": "Market participation spot evidence is incomplete",
        }
    if direction != expected_direction:
        return {
            **base,
            "status": "DIRECTION_CONFLICT",
            "reason": (
                f"Market participation trend is {direction}; "
                f"{normalized_side} requires {expected_direction}"
            ),
        }
    if confidence < MARKET_PARTICIPATION_EXECUTION_THRESHOLD:
        return {
            **base,
            "status": "BELOW_THRESHOLD",
            "reason": "Market participation confidence is below 40%",
        }
    return {
        **base,
        "allowed": True,
        "status": "ALIGNED",
        "reason": (
            f"Market participation confirms {normalized_side} "
            f"at {confidence:.0f}% confidence"
        ),
    }


def market_participation_blockers(payload, side):
    decision = evaluate_market_participation(payload, side)
    return [] if decision["allowed"] else [decision["reason"]]


def _normalize_side(value):
    side = str(value or "").upper()
    if side in {"BUY", "LONG", "STRONG_LONG"}:
        return "LONG"
    if side in {"SELL", "SHORT", "STRONG_SHORT"}:
        return "SHORT"
    return side or None


def _number(value, fallback=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(fallback)
