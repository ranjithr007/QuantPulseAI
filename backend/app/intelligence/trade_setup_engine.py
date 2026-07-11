from app.intelligence.multi_timeframe_engine import BEARISH_BIASES
from app.intelligence.multi_timeframe_engine import BULLISH_BIASES

LONG_PERMISSIONS = {"LONG_ALLOWED", "LONG_ONLY"}
SHORT_PERMISSIONS = {"SHORT_ALLOWED", "SHORT_ONLY"}
LONG_READY_5M_BIASES = {"LONG", "WEAK_LONG", "NEUTRAL"}
SHORT_READY_5M_BIASES = {"SHORT", "WEAK_SHORT", "NEUTRAL"}
LONG_ORDERFLOW_CONFIRMATION = "BUYERS_CONTROL"
SHORT_ORDERFLOW_CONFIRMATION = "SELLERS_CONTROL"
CONFIDENCE_WINDOWS = {
    "1m": {"min": 52.0, "preferred": 60.0, "max": 76.0},
    "5m": {"min": 55.0, "preferred": 65.0, "max": 78.0},
    "15m": {"min": 58.0, "preferred": 68.0, "max": 80.0},
    "1h": {"min": 60.0, "preferred": 70.0, "max": 82.0},
    "4h": {"min": 62.0, "preferred": 72.0, "max": 84.0},
    "1d": {"min": 65.0, "preferred": 75.0, "max": 86.0},
}
DEFAULT_CONFIDENCE_WINDOW = {"min": 60.0, "preferred": 70.0, "max": 82.0}


def build_trade_setup_decision(confirmation, timeframes):
    lower = _lower_timeframe(timeframes)
    confidence_window = _confidence_window(lower)
    permission = confirmation["trade_permission"]

    if permission == "BLOCKED":
        return {
            "status": "BLOCKED",
            "side": None,
            "reason": confirmation["reason"],
            "confidence_window": confidence_window,
        }

    if permission in LONG_PERMISSIONS:
        return _directional_setup(
            side="LONG",
            lower=lower,
            ready_biases=LONG_READY_5M_BIASES,
            wait_reason=f"Waiting for {lower['timeframe']} pullback to stabilize before long setup",
            confidence_window=confidence_window,
        )

    if permission in SHORT_PERMISSIONS:
        return _directional_setup(
            side="SHORT",
            lower=lower,
            ready_biases=SHORT_READY_5M_BIASES,
            wait_reason=f"Waiting for {lower['timeframe']} bounce to stabilize before short setup",
            confidence_window=confidence_window,
        )

    return {
        "status": "WAIT",
        "side": None,
        "reason": confirmation["reason"],
        "confidence_window": confidence_window,
    }


def build_entry_trigger_decision(confirmation, timeframes):
    setup = build_trade_setup_decision(confirmation, timeframes)

    if setup["side"] is None:
        return {
            "status": setup["status"],
            "side": None,
            "reason": setup["reason"],
            "conditions": [],
            "confidence_window": setup.get("confidence_window"),
        }

    lower = _lower_timeframe(timeframes)
    stack_confidence = _stack_confidence(timeframes)
    confidence_window = setup.get("confidence_window") or _confidence_window(lower)
    timing_timeframes = confirmation.get("entry_timeframes") or []
    conditions = _directional_trigger_conditions(
        side=setup["side"],
        permission=confirmation["trade_permission"],
        lower=lower,
        confidence_window=confidence_window,
        stack_confidence=stack_confidence,
        timing_timeframes=timing_timeframes,
    )
    is_ready = all(condition["passed"] for condition in conditions)

    return {
        "status": "READY" if is_ready else "WAIT",
        "side": setup["side"],
        "confidence_window": confidence_window,
        "stack_confidence": round(stack_confidence, 2),
        "reason": (
            f"{setup['side']} entry trigger is ready"
            if is_ready
            else _first_failed_condition_message(conditions)
        ),
        "conditions": conditions,
    }


def _directional_setup(side, lower, ready_biases, wait_reason, confidence_window=None):
    if lower is None or lower.get("signal") == "NO_DATA":
        return {
            "status": "BLOCKED",
            "side": None,
            "reason": "5m signal data is missing",
            "confidence_window": confidence_window,
        }

    if lower["bias"] in ready_biases:
        return {
            "status": "READY",
            "side": side,
            "reason": f"{side} setup is aligned with multi-timeframe permission",
            "confidence_window": confidence_window,
        }

    return {
        "status": "WAIT",
        "side": side,
        "reason": wait_reason,
        "confidence_window": confidence_window,
    }


def _directional_trigger_conditions(side, permission, lower, confidence_window, stack_confidence, timing_timeframes):
    if side == "LONG":
        ready_biases = LONG_READY_5M_BIASES
        permissions = LONG_PERMISSIONS
        orderflow_message = f"{lower['timeframe']} orderflow should show buyers control"
    else:
        ready_biases = SHORT_READY_5M_BIASES
        permissions = SHORT_PERMISSIONS
        orderflow_message = f"{lower['timeframe']} orderflow should show sellers control"

    return [
        {
            "name": "multi_timeframe_permission",
            "passed": permission in permissions,
            "message": f"Multi-timeframe permission should allow {side}",
        },
        {
            "name": "lower_timeframe_bias",
            "passed": lower is not None and lower.get("bias") in ready_biases,
            "message": f"{lower['timeframe']} bias should stabilize for {side}",
            "actual": lower.get("bias") if lower else None,
        },
        {
            "name": "orderflow_confirmation",
            "passed": _orderflow_supports_side(lower, side),
            "message": orderflow_message,
            "actual": _component_value(lower, "orderflow"),
        },
        {
            "name": "confidence_window",
            "passed": _confidence_in_window(lower, confidence_window, stack_confidence),
            "message": (
                f"{lower['timeframe']} confidence or stack confidence should stay in the "
                f"{int(confidence_window['min'])}-{int(confidence_window['max'])} band "
                f"(sweet spot {int(confidence_window['preferred'])})"
            ),
            "actual": _confidence_value(lower),
            "stack_confidence": round(stack_confidence, 2),
            "window": confidence_window,
        },
        {
            "name": "freshness",
            "passed": _is_fresh(lower),
            "message": f"{lower['timeframe']} signal and inputs should be fresh",
        },
        {
            "name": "entry_timing_confirmation",
            "passed": _timing_supports_side(timing_timeframes, side),
            "message": _timing_message(side, timing_timeframes),
            "actual": _timing_actual(timing_timeframes),
        },
    ]


def _component_value(timeframe, component):
    if not timeframe:
        return None

    return (
        timeframe.get("component_scores", {})
        .get(component, {})
        .get("value")
    )


def _component_score(timeframe, component):
    if not timeframe:
        return 0

    return (
        timeframe.get("component_scores", {})
        .get(component, {})
        .get("score", 0)
    )


def _confidence_value(timeframe):
    if not timeframe:
        return 0

    return float(timeframe.get("confidence") or 0)


def _confidence_at_least(timeframe, minimum):
    return _confidence_value(timeframe) >= float(minimum)


def _confidence_in_window(timeframe, confidence_window, stack_confidence=None):
    if confidence_window is None:
        return False

    if not timeframe:
        return False

    raw_confidence = timeframe.get("confidence")
    if raw_confidence is None and not float(stack_confidence or 0):
        return True

    confidence = _confidence_value(timeframe)
    candidate = max(confidence, float(stack_confidence or 0))
    return candidate >= float(confidence_window["min"])


def _confidence_window(timeframe):
    if not timeframe:
        return dict(DEFAULT_CONFIDENCE_WINDOW)

    timeframe_label = str(timeframe.get("timeframe") or "").lower()
    window = CONFIDENCE_WINDOWS.get(timeframe_label)
    if window:
        return dict(window)

    return dict(DEFAULT_CONFIDENCE_WINDOW)


def _stack_confidence(timeframes):
    if not timeframes:
        return 0.0

    weights = [0.5, 0.3, 0.2]
    total = 0.0
    weight_sum = 0.0

    for item, weight in zip(timeframes, weights):
        total += _confidence_value(item) * weight
        weight_sum += weight

    if weight_sum <= 0:
        return 0.0

    return total / weight_sum


def _timing_supports_side(timeframes, side):
    if not timeframes:
        return True

    opposing_biases = BEARISH_BIASES if side == "LONG" else BULLISH_BIASES

    for item in timeframes:
        bias = item.get("bias") if item else None
        if bias in opposing_biases:
            return False

    return True


def _timing_message(side, timeframes):
    if not timeframes:
        return f"No lower-timeframe timing layer required for {side}"

    timeframe_labels = ", ".join(item["timeframe"] for item in timeframes if item)
    return f"Lower-timeframe timing on {timeframe_labels} should not conflict with {side}"


def _timing_actual(timeframes):
    if not timeframes:
        return []

    return [
        {
            "timeframe": item.get("timeframe"),
            "bias": item.get("bias"),
            "signal": item.get("signal"),
        }
        for item in timeframes
    ]


def _orderflow_supports_side(timeframe, side):
    value = _component_value(timeframe, "orderflow")
    score = _component_score(timeframe, "orderflow")

    if side == "LONG":
        return value == LONG_ORDERFLOW_CONFIRMATION or score > 0

    return value == SHORT_ORDERFLOW_CONFIRMATION or score < 0


def _is_fresh(timeframe):
    if not timeframe:
        return False

    if timeframe.get("freshness", {}).get("is_stale", True):
        return False

    return not any(
        item.get("is_stale", True)
        for item in timeframe.get("inputs", {}).values()
    )


def _first_failed_condition_message(conditions):
    for condition in conditions:
        if not condition["passed"]:
            return condition["message"]

    return "Entry trigger is waiting"


def _get_timeframe(timeframes, timeframe):
    for item in timeframes:
        if item["timeframe"] == timeframe:
            return item

    return None


def _lower_timeframe(timeframes):
    return timeframes[0] if timeframes else None
