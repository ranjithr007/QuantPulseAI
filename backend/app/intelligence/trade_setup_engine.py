from app.intelligence.multi_timeframe_engine import BEARISH_BIASES
from app.intelligence.multi_timeframe_engine import BULLISH_BIASES
from app.governance.evidence_policy import FULL_SIZE_ENTRY_CONFIDENCE
from app.governance.evidence_policy import MIN_ENTRY_CONFIDENCE
from app.governance.evidence_policy import OFFICIAL_ENTRY_TIMEFRAMES

LONG_PERMISSIONS = {"LONG_ALLOWED", "LONG_ONLY"}
SHORT_PERMISSIONS = {"SHORT_ALLOWED", "SHORT_ONLY"}
LONG_READY_ENTRY_BIASES = {"LONG", "WEAK_LONG", "NEUTRAL"}
SHORT_READY_ENTRY_BIASES = {"SHORT", "WEAK_SHORT", "NEUTRAL"}
LONG_ORDERFLOW_CONFIRMATION = "BUYERS_CONTROL"
SHORT_ORDERFLOW_CONFIRMATION = "SELLERS_CONTROL"
CONFIDENCE_WINDOWS = {
    "1m": {"min": 52.0, "preferred": 60.0, "max": 76.0},
    "5m": {"min": 55.0, "preferred": 65.0, "max": 78.0},
    "15m": {"min": 58.0, "preferred": 68.0, "max": 80.0},
    **{
        timeframe: {
            "min": MIN_ENTRY_CONFIDENCE,
            "preferred": FULL_SIZE_ENTRY_CONFIDENCE,
            "max": 100.0,
        }
        for timeframe in OFFICIAL_ENTRY_TIMEFRAMES
    },
}
DEFAULT_CONFIDENCE_WINDOW = {
    "min": MIN_ENTRY_CONFIDENCE,
    "preferred": FULL_SIZE_ENTRY_CONFIDENCE,
    "max": 100.0,
}
TIMEFRAME_DURABILITY = {"1h": 1, "2h": 2, "4h": 3, "1d": 4}


def build_trade_setup_decision(confirmation, timeframes):
    if _is_governed_timeframe_stack(timeframes):
        return _build_governed_trade_setup_decision(confirmation, timeframes)

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
            ready_biases=LONG_READY_ENTRY_BIASES,
            wait_reason=f"Waiting for {lower['timeframe']} pullback to stabilize before long setup",
            confidence_window=confidence_window,
        )

    if permission in SHORT_PERMISSIONS:
        return _directional_setup(
            side="SHORT",
            lower=lower,
            ready_biases=SHORT_READY_ENTRY_BIASES,
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
    if _is_governed_timeframe_stack(timeframes):
        return _build_governed_entry_trigger_decision(confirmation, timeframes)

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
            "reason": "Entry timeframe signal data is missing",
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
        ready_biases = LONG_READY_ENTRY_BIASES
        permissions = LONG_PERMISSIONS
        orderflow_message = f"{lower['timeframe']} orderflow should show buyers control"
    else:
        ready_biases = SHORT_READY_ENTRY_BIASES
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
            "name": "core_input_confirmation",
            "passed": _core_inputs_allow_trade(lower),
            "message": _core_input_message(lower),
            "actual": _core_input_status(lower),
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


def _build_governed_trade_setup_decision(confirmation, timeframes):
    permission = confirmation.get("trade_permission")
    if permission == "BLOCKED":
        return {
            "status": "BLOCKED",
            "side": None,
            "reason": confirmation.get("reason") or "Required timeframe data is unavailable",
            "confidence_window": dict(DEFAULT_CONFIDENCE_WINDOW),
            "entry_timeframe": None,
        }

    directional = [item for item in timeframes if _actionable_side(item)]
    if not directional:
        return {
            "status": "WAIT",
            "side": None,
            "reason": "No governed timeframe has a score outside the WAIT band",
            "confidence_window": dict(DEFAULT_CONFIDENCE_WINDOW),
            "entry_timeframe": None,
        }

    candidates = [
        item
        for item in directional
        if _confidence_in_window(item, _confidence_window(item))
        and _core_inputs_allow_trade(item)
    ]
    if not candidates:
        selected = max(directional, key=_governed_candidate_rank)
        reason = (
            _core_input_message(selected)
            if not _core_inputs_allow_trade(selected)
            else (
                f"{selected['timeframe']} confidence must be at least "
                f"{int(MIN_ENTRY_CONFIDENCE)}%"
            )
        )
        return {
            "status": "WAIT",
            "side": _actionable_side(selected),
            "reason": reason,
            "confidence_window": _confidence_window(selected),
            "entry_timeframe": selected.get("timeframe"),
            "selected_timeframe": selected.get("timeframe"),
            "candidate_count": 0,
        }

    selected = max(candidates, key=_governed_candidate_rank)
    side = _actionable_side(selected)
    return {
        "status": "READY",
        "side": side,
        "reason": (
            f"{selected['timeframe']} {side} setup is the strongest governed opportunity"
        ),
        "confidence_window": _confidence_window(selected),
        "entry_timeframe": selected.get("timeframe"),
        "selected_timeframe": selected.get("timeframe"),
        "candidate_count": len(candidates),
    }


def _build_governed_entry_trigger_decision(confirmation, timeframes):
    permission = confirmation.get("trade_permission")
    timing_timeframes = confirmation.get("entry_timeframes") or []
    evaluations = []

    for item in timeframes:
        side = _actionable_side(item)
        confidence_window = _confidence_window(item)
        if side is None:
            evaluations.append(
                {
                    "timeframe": item.get("timeframe"),
                    "status": "WAIT",
                    "side": None,
                    "confidence": _confidence_value(item),
                    "score": float(item.get("score") or 0),
                    "reason": "Timeframe score is inside the WAIT band",
                    "conditions": [],
                    "confidence_window": confidence_window,
                }
            )
            continue

        conditions = _governed_trigger_conditions(
            side=side,
            permission=permission,
            timeframe=item,
            confidence_window=confidence_window,
            timing_timeframes=timing_timeframes,
        )
        ready = all(condition["passed"] for condition in conditions)
        evaluations.append(
            {
                "timeframe": item.get("timeframe"),
                "status": "READY" if ready else "WAIT",
                "side": side,
                "confidence": _confidence_value(item),
                "score": float(item.get("score") or 0),
                "reason": (
                    f"{item.get('timeframe')} {side} entry trigger is ready"
                    if ready
                    else _first_failed_condition_message(conditions)
                ),
                "conditions": conditions,
                "confidence_window": confidence_window,
                "candle_time": item.get("candle_time"),
            }
        )

    directional = [item for item in evaluations if item.get("side")]
    ready = [item for item in directional if item.get("status") == "READY"]
    pool = ready or directional

    if not pool:
        return {
            "status": "BLOCKED" if permission == "BLOCKED" else "WAIT",
            "side": None,
            "reason": confirmation.get("reason") or "No governed timeframe has an actionable direction",
            "conditions": [],
            "confidence_window": dict(DEFAULT_CONFIDENCE_WINDOW),
            "selected_confidence": None,
            "entry_timeframe": None,
            "selected_timeframe": None,
            "timeframe_candidates": evaluations,
        }

    selected = max(pool, key=_governed_evaluation_rank)
    is_ready = selected.get("status") == "READY"
    return {
        "status": "READY" if is_ready else "BLOCKED" if permission == "BLOCKED" else "WAIT",
        "side": selected.get("side"),
        "reason": selected.get("reason"),
        "conditions": selected.get("conditions") or [],
        "confidence_window": selected.get("confidence_window"),
        "selected_confidence": selected.get("confidence"),
        "entry_timeframe": selected.get("timeframe"),
        "selected_timeframe": selected.get("timeframe"),
        "timeframe_candidates": evaluations,
    }


def _governed_trigger_conditions(side, permission, timeframe, confidence_window, timing_timeframes):
    orderflow_message = (
        f"{timeframe['timeframe']} orderflow should show "
        f"{'buyers' if side == 'LONG' else 'sellers'} control"
    )
    return [
        {
            "name": "governed_timeframe_scan",
            "passed": permission != "BLOCKED",
            "message": "All governed timeframes must be scanned with available data",
            "actual": permission,
        },
        {
            "name": "timeframe_direction",
            "passed": _actionable_side(timeframe) == side,
            "message": f"{timeframe['timeframe']} must have an actionable {side} score",
            "actual": timeframe.get("signal"),
        },
        {
            "name": "core_input_confirmation",
            "passed": _core_inputs_allow_trade(timeframe),
            "message": _core_input_message(timeframe),
            "actual": _core_input_status(timeframe),
        },
        {
            "name": "orderflow_confirmation",
            "passed": _orderflow_supports_side(timeframe, side),
            "message": orderflow_message,
            "actual": _component_value(timeframe, "orderflow"),
        },
        {
            "name": "confidence_window",
            "passed": _confidence_in_window(timeframe, confidence_window),
            "message": (
                f"{timeframe['timeframe']} confidence must be at least "
                f"{int(MIN_ENTRY_CONFIDENCE)}% (full size at "
                f"{int(FULL_SIZE_ENTRY_CONFIDENCE)}%)"
            ),
            "actual": _confidence_value(timeframe),
            "window": confidence_window,
        },
        {
            "name": "freshness",
            "passed": _is_fresh(timeframe),
            "message": f"{timeframe['timeframe']} signal and inputs should be fresh",
        },
        {
            "name": "entry_timing_confirmation",
            "passed": _timing_supports_side(timing_timeframes, side),
            "message": _timing_message(side, timing_timeframes),
            "actual": _timing_actual(timing_timeframes),
        },
    ]


def _is_governed_timeframe_stack(timeframes):
    labels = tuple(str(item.get("timeframe") or "").lower() for item in (timeframes or []))
    return labels == tuple(OFFICIAL_ENTRY_TIMEFRAMES)


def _core_inputs_allow_trade(timeframe):
    """Make contradiction diagnostics authoritative at setup boundaries."""
    contradiction = (timeframe or {}).get("contradiction")
    if not isinstance(contradiction, dict) or not contradiction:
        return True
    status = str(contradiction.get("status") or "").upper()
    return contradiction.get("trade_allowed") is not False and status not in {
        "INVALIDATED",
        "FAILED",
        "ERROR",
        "UNAVAILABLE",
    }


def _core_input_status(timeframe):
    contradiction = (timeframe or {}).get("contradiction") or {}
    return contradiction.get("status") or (
        "ALLOWED" if _core_inputs_allow_trade(timeframe) else "INVALIDATED"
    )


def _core_input_message(timeframe):
    contradiction = (timeframe or {}).get("contradiction") or {}
    reasons = contradiction.get("reasons") or []
    if reasons:
        return str(reasons[0])
    summary = contradiction.get("summary")
    if summary:
        return str(summary)
    label = (timeframe or {}).get("timeframe") or "Entry timeframe"
    return f"{label} core inputs must be fresh and available"


def _actionable_side(timeframe):
    if not timeframe:
        return None
    score = timeframe.get("score")
    if score is not None:
        score = float(score)
        if score >= MIN_ENTRY_CONFIDENCE:
            return "LONG"
        if score <= -MIN_ENTRY_CONFIDENCE:
            return "SHORT"
        return None
    signal = str(timeframe.get("signal") or "").upper()
    if signal in {"LONG", "BUY", "STRONG_LONG"}:
        return "LONG"
    if signal in {"SHORT", "SELL", "STRONG_SHORT"}:
        return "SHORT"
    return None


def _governed_candidate_rank(item):
    return (
        _confidence_value(item),
        abs(float(item.get("score") or 0)),
        TIMEFRAME_DURABILITY.get(str(item.get("timeframe") or "").lower(), 0),
        _timestamp_rank(item.get("candle_time")),
    )


def _governed_evaluation_rank(item):
    return (
        float(item.get("confidence") or 0),
        abs(float(item.get("score") or 0)),
        TIMEFRAME_DURABILITY.get(str(item.get("timeframe") or "").lower(), 0),
        _timestamp_rank(item.get("candle_time")),
    )


def _timestamp_rank(value):
    return value.timestamp() if hasattr(value, "timestamp") else 0.0


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

    configured_weights = {"1h": 0.15, "2h": 0.20, "4h": 0.25, "1d": 0.40}
    total = 0.0
    weight_sum = 0.0

    for item in timeframes:
        weight = configured_weights.get(str(item.get("timeframe") or "").lower(), 0.0)
        if weight <= 0:
            continue
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
