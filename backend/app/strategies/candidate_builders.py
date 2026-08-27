"""Independent governed strategy candidate builders.

These builders transform immutable scan evidence into strategy-owned payloads.
They never read mutable state, approve risk, or execute a trade.
"""

from app.governance.evidence_policy import MIN_ENTRY_CONFIDENCE
from app.governance.evidence_policy import OFFICIAL_ENTRY_TIMEFRAMES
from app.trading.market_participation_guard import (
    MARKET_PARTICIPATION_MAX_AGE_SECONDS,
)
from app.trading.trade_plan_engine import build_trade_plan
from app.utils.freshness import freshness_status
from app.utils.signal_validation import validate_trade_plan_direction


TIMEFRAME_DURABILITY = {"1h": 1, "2h": 2, "4h": 3, "1d": 4}


def build_regime_trend_payload(core_payload):
    return _build_component_payload(
        core_payload,
        label="Regime Trend",
        required_components=("feature", "regime"),
        maximum_component_total=49.0,
    )


def build_orderflow_smc_payload(core_payload):
    return _build_component_payload(
        core_payload,
        label="Order Flow SMC",
        required_components=("orderflow", "smc"),
        maximum_component_total=53.0,
    )


def build_liquidation_carry_payload(core_payload, market_participation):
    raw = market_participation or {}
    derivatives = raw.get("derivatives") or {}
    liquidation = raw.get("liquidation") or {}
    components = raw.get("components") or {}
    derivative_score = _number(components.get("derivatives"))
    liquidation_score = _number(components.get("liquidation"))
    funding = _optional_number(derivatives.get("funding_rate"))
    open_interest = _optional_number(
        derivatives.get("open_interest_change_percent")
    )
    observed_liquidation = (
        liquidation.get("data_quality") == "OBSERVED"
        and str(liquidation.get("status") or "").upper() == "READY"
    )
    fresh = not freshness_status(
        raw.get("effective_timestamp"),
        MARKET_PARTICIPATION_MAX_AGE_SECONDS,
    ).get("is_stale", True)
    evidence_ready = bool(
        raw.get("status") == "READY"
        and raw.get("quality_state") == "OK"
        and fresh
        and funding is not None
        and open_interest is not None
        and observed_liquidation
    )
    aligned = bool(
        derivative_score
        and liquidation_score
        and derivative_score * liquidation_score > 0
    )
    score = _clamp(
        (derivative_score + liquidation_score) / 23.0 * 100.0,
        -100.0,
        100.0,
    )
    side = _side(score) if evidence_ready and aligned else None
    selected = _select_spot_timeframe(raw, side)
    blocked_reasons = []
    if raw.get("status") != "READY" or raw.get("quality_state") != "OK":
        blocked_reasons.append("Market participation spot evidence is incomplete")
    if not fresh:
        blocked_reasons.append("Liquidation Carry evidence is stale")
    if funding is None:
        blocked_reasons.append("Fresh funding evidence is unavailable")
    if open_interest is None:
        blocked_reasons.append("Open-interest change evidence is unavailable")
    if not observed_liquidation:
        blocked_reasons.append("Observed liquidation evidence is unavailable")
    if evidence_ready and not aligned:
        blocked_reasons.append(
            "Derivatives and liquidation pressure do not confirm the same direction"
        )
    if evidence_ready and aligned and side is None:
        blocked_reasons.append("Liquidation Carry score is inside the WAIT band")
    if selected is None:
        blocked_reasons.append("No fresh spot timeframe price is available for entry")

    confidence = round(abs(score), 2)
    timeframes = _normalized_spot_timeframes(raw)
    selected_timeframe = (selected or {}).get("timeframe")
    for item in timeframes:
        if item.get("timeframe") == selected_timeframe:
            item["spot_score"] = item.get("score")
            item["score"] = round(score, 2)
            item["confidence"] = confidence
            item["bias"] = _direction(score)
            item["signal"] = side or "WAIT"
            selected = item
            break
    trade_plan = _trade_plan(
        core_payload,
        selected,
        side,
        confidence,
    )
    validation = _validation(side, trade_plan, blocked_reasons)
    ready = not blocked_reasons and validation["is_valid"]
    return {
        "symbol": core_payload["symbol"],
        "source": "liquidation_carry_strategy",
        "mode": core_payload.get("mode") or "intraday",
        "timeframes_used": [item.get("timeframe") for item in timeframes],
        "timeframes": timeframes,
        "confirmation": {
            "confidence": confidence,
            "overall_bias": _direction(score),
        },
        "trigger": {
            "status": "READY" if ready else "WAIT",
            "side": side,
            "entry_timeframe": (selected or {}).get("timeframe"),
            "reason": (
                "Liquidation Carry entry trigger is ready"
                if ready
                else blocked_reasons[0]
                if blocked_reasons
                else "Liquidation Carry trade plan is invalid"
            ),
            "conditions": [],
        },
        "trade_plan": trade_plan,
        "trade_plan_validation": validation,
        "strategy_score": round(score, 2),
        "strategy_components": {
            "derivatives": derivative_score,
            "liquidation": liquidation_score,
            "funding_rate": funding,
            "open_interest_change_percent": open_interest,
        },
        "market_participation": raw,
        "data_generation_id": raw.get("data_generation_id"),
        "effective_timestamp": raw.get("effective_timestamp"),
    }


def _build_component_payload(
    core_payload,
    *,
    label,
    required_components,
    maximum_component_total,
):
    timeframes = [
        _component_timeframe(
            item,
            required_components,
            maximum_component_total,
        )
        for item in core_payload.get("timeframes") or []
    ]
    labels = tuple(item.get("timeframe") for item in timeframes)
    complete_stack = labels == tuple(OFFICIAL_ENTRY_TIMEFRAMES)
    actionable = [
        item
        for item in timeframes
        if item.get("status") == "OK" and _side(item.get("score"))
    ]
    selected = max(actionable, key=_candidate_rank, default=None)
    blocked_reasons = []
    if not complete_stack:
        blocked_reasons.append("All governed timeframes must be scanned")
    if selected is None:
        details = next(
            (
                item.get("reason")
                for item in timeframes
                if item.get("reason")
            ),
            None,
        )
        blocked_reasons.append(
            details or f"{label} score is inside the WAIT band"
        )
    side = _side((selected or {}).get("score"))
    confidence = abs(float((selected or {}).get("score") or 0))
    trade_plan = _trade_plan(
        core_payload,
        selected,
        side,
        confidence,
    )
    validation = _validation(side, trade_plan, blocked_reasons)
    ready = not blocked_reasons and validation["is_valid"]
    return {
        "symbol": core_payload["symbol"],
        "source": label.lower().replace(" ", "_") + "_strategy",
        "mode": core_payload.get("mode") or "intraday",
        "timeframes_used": list(OFFICIAL_ENTRY_TIMEFRAMES),
        "timeframes": timeframes,
        "confirmation": {
            "confidence": round(confidence, 2),
            "overall_bias": _direction((selected or {}).get("score")),
        },
        "trigger": {
            "status": "READY" if ready else "WAIT",
            "side": side,
            "entry_timeframe": (selected or {}).get("timeframe"),
            "reason": (
                f"{label} entry trigger is ready"
                if ready
                else blocked_reasons[0]
                if blocked_reasons
                else f"{label} trade plan is invalid"
            ),
            "conditions": [],
        },
        "trade_plan": trade_plan,
        "trade_plan_validation": validation,
        "data_generation_id": core_payload.get("data_generation_id"),
    }


def _component_timeframe(item, required_components, maximum_component_total):
    component_map = item.get("component_scores") or {}
    selected_components = {
        name: component_map.get(name) or {}
        for name in required_components
    }
    scores = [
        _number(selected_components[name].get("score"))
        for name in required_components
    ]
    present = all(
        selected_components[name].get("value") is not None
        or selected_components[name].get("reason")
        for name in required_components
    )
    inputs = item.get("inputs") or {}
    fresh = bool(
        not (item.get("freshness") or {}).get("is_stale", True)
        and all(
            name in inputs and not (inputs.get(name) or {}).get("is_stale", True)
            for name in required_components
        )
    )
    aligned = bool(
        scores
        and (
            all(score > 0 for score in scores)
            or all(score < 0 for score in scores)
        )
    )
    score = _clamp(
        sum(scores) / float(maximum_component_total) * 100.0,
        -100.0,
        100.0,
    )
    status = "OK" if present and fresh and aligned else "WAIT"
    reason = None
    if not present:
        reason = "Required strategy components are unavailable"
    elif not fresh:
        reason = "Required strategy components are stale"
    elif not aligned:
        reason = "Required strategy components disagree on direction"
    elif abs(score) < MIN_ENTRY_CONFIDENCE:
        reason = "Strategy score is inside the WAIT band"
    return {
        **item,
        "status": status,
        "score": round(score, 2),
        "confidence": round(abs(score), 2),
        "signal": _side(score) or "WAIT",
        "bias": _direction(score),
        "component_scores": selected_components,
        "strategy_components": selected_components,
        "reason": reason,
    }


def _normalized_spot_timeframes(raw):
    return [
        {
            **item,
            "status": "OK" if item.get("status") == "READY" else item.get("status"),
            "candle_time": item.get("source_timestamp"),
            "current_price": item.get("spot_price"),
            "confidence": abs(_number(item.get("score"))),
            "bias": item.get("direction"),
        }
        for item in ((raw.get("spot") or {}).get("timeframes") or [])
    ]


def _select_spot_timeframe(raw, side):
    timeframes = _normalized_spot_timeframes(raw)
    expected = 1 if side == "LONG" else -1 if side == "SHORT" else 0
    aligned = [
        item
        for item in timeframes
        if item.get("status") == "OK"
        and _number(item.get("score")) * expected > 0
        and _number(item.get("current_price")) > 0
    ]
    return max(aligned, key=_candidate_rank, default=None)


def _trade_plan(core_payload, selected, side, confidence):
    if selected is None or side is None:
        return None
    price = _number(selected.get("current_price") or selected.get("spot_price"))
    if price <= 0:
        return None
    return build_trade_plan(
        side,
        price,
        confidence=confidence,
        symbol=core_payload["symbol"],
        timeframe=selected.get("timeframe"),
    )


def _validation(side, trade_plan, blocked_reasons):
    if blocked_reasons or side is None or trade_plan is None:
        return {
            "is_valid": False,
            "errors": list(blocked_reasons) or ["Strategy did not produce a trade plan"],
        }
    return validate_trade_plan_direction(
        side,
        trade_plan.get("entry"),
        trade_plan.get("target1"),
    )


def _candidate_rank(item):
    return (
        abs(_number(item.get("score"))),
        TIMEFRAME_DURABILITY.get(str(item.get("timeframe") or "").lower(), 0),
        _timestamp_rank(item.get("candle_time") or item.get("source_timestamp")),
    )


def _timestamp_rank(value):
    return value.timestamp() if hasattr(value, "timestamp") else 0.0


def _side(score):
    score = _number(score)
    if score >= MIN_ENTRY_CONFIDENCE:
        return "LONG"
    if score <= -MIN_ENTRY_CONFIDENCE:
        return "SHORT"
    return None


def _direction(score):
    side = _side(score)
    return "BULLISH" if side == "LONG" else "BEARISH" if side == "SHORT" else "NEUTRAL"


def _optional_number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _number(value):
    parsed = _optional_number(value)
    return parsed if parsed is not None else 0.0


def _clamp(value, minimum, maximum):
    return max(minimum, min(maximum, float(value)))
