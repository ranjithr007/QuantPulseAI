LONG_PERMISSIONS = {"LONG_ALLOWED", "LONG_ONLY"}
SHORT_PERMISSIONS = {"SHORT_ALLOWED", "SHORT_ONLY"}
LONG_READY_5M_BIASES = {"LONG", "WEAK_LONG", "NEUTRAL"}
SHORT_READY_5M_BIASES = {"SHORT", "WEAK_SHORT", "NEUTRAL"}
LONG_ORDERFLOW_CONFIRMATION = "BUYERS_CONTROL"
SHORT_ORDERFLOW_CONFIRMATION = "SELLERS_CONTROL"


def build_trade_setup_decision(confirmation, timeframes):
    lower = _lower_timeframe(timeframes)
    permission = confirmation["trade_permission"]

    if permission == "BLOCKED":
        return {
            "status": "BLOCKED",
            "side": None,
            "reason": confirmation["reason"],
        }

    if permission in LONG_PERMISSIONS:
        return _directional_setup(
            side="LONG",
            lower=lower,
            ready_biases=LONG_READY_5M_BIASES,
            wait_reason=f"Waiting for {lower['timeframe']} pullback to stabilize before long setup",
        )

    if permission in SHORT_PERMISSIONS:
        return _directional_setup(
            side="SHORT",
            lower=lower,
            ready_biases=SHORT_READY_5M_BIASES,
            wait_reason=f"Waiting for {lower['timeframe']} bounce to stabilize before short setup",
        )

    return {
        "status": "WAIT",
        "side": None,
        "reason": confirmation["reason"],
    }


def build_entry_trigger_decision(confirmation, timeframes):
    setup = build_trade_setup_decision(confirmation, timeframes)

    if setup["side"] is None:
        return {
            "status": setup["status"],
            "side": None,
            "reason": setup["reason"],
            "conditions": [],
        }

    lower = _lower_timeframe(timeframes)
    conditions = _directional_trigger_conditions(
        side=setup["side"],
        permission=confirmation["trade_permission"],
        lower=lower,
    )
    is_ready = all(condition["passed"] for condition in conditions)

    return {
        "status": "READY" if is_ready else "WAIT",
        "side": setup["side"],
        "reason": (
            f"{setup['side']} entry trigger is ready"
            if is_ready
            else _first_failed_condition_message(conditions)
        ),
        "conditions": conditions,
    }


def _directional_setup(side, lower, ready_biases, wait_reason):
    if lower is None or lower.get("signal") == "NO_DATA":
        return {
            "status": "BLOCKED",
            "side": None,
            "reason": "5m signal data is missing",
        }

    if lower["bias"] in ready_biases:
        return {
            "status": "READY",
            "side": side,
            "reason": f"{side} setup is aligned with multi-timeframe permission",
        }

    return {
        "status": "WAIT",
        "side": side,
        "reason": wait_reason,
    }


def _directional_trigger_conditions(side, permission, lower):
    if side == "LONG":
        ready_biases = LONG_READY_5M_BIASES
        permissions = LONG_PERMISSIONS
        orderflow_value = LONG_ORDERFLOW_CONFIRMATION
        orderflow_message = f"{lower['timeframe']} orderflow should show buyers control"
    else:
        ready_biases = SHORT_READY_5M_BIASES
        permissions = SHORT_PERMISSIONS
        orderflow_value = SHORT_ORDERFLOW_CONFIRMATION
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
            "passed": _component_value(lower, "orderflow") == orderflow_value,
            "message": orderflow_message,
            "actual": _component_value(lower, "orderflow"),
        },
        {
            "name": "freshness",
            "passed": _is_fresh(lower),
            "message": f"{lower['timeframe']} signal and inputs should be fresh",
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
