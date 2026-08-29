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
TREND_PULLBACK_REGIMES = {"BULL_PULLBACK": "LONG", "BEAR_RALLY": "SHORT"}
RANGE_REVERSION_REGIMES = {
    "RANGE_ACCUMULATION": "LONG",
    "RANGE_DISTRIBUTION": "SHORT",
}


def build_trend_pullback_payload(core_payload, market_participation):
    return _build_location_strategy_payload(
        core_payload,
        market_participation,
        label="Trend Pullback",
        execution_profile="TREND_PULLBACK",
        allowed_regimes=TREND_PULLBACK_REGIMES,
    )


def build_range_reversion_payload(core_payload, market_participation):
    return _build_location_strategy_payload(
        core_payload,
        market_participation,
        label="Range Reversion",
        execution_profile="RANGE_REVERSION",
        allowed_regimes=RANGE_REVERSION_REGIMES,
    )


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


def _build_location_strategy_payload(
    core_payload,
    market_participation,
    *,
    label,
    execution_profile,
    allowed_regimes,
):
    spot_by_timeframe = {
        str(item.get("timeframe") or "").lower(): item
        for item in (
            ((market_participation or {}).get("spot") or {}).get("timeframes")
            or []
        )
    }
    timeframes = [
        _location_timeframe(
            item,
            spot_by_timeframe.get(str(item.get("timeframe") or "").lower()),
            execution_profile=execution_profile,
            allowed_regimes=allowed_regimes,
        )
        for item in (core_payload.get("timeframes") or [])
    ]
    labels = tuple(item.get("timeframe") for item in timeframes)
    blocked_reasons = []
    if labels != tuple(OFFICIAL_ENTRY_TIMEFRAMES):
        blocked_reasons.append("All governed timeframes must be scanned")
    if str(core_payload.get("mode") or "intraday").lower() != "intraday":
        blocked_reasons.append(
            f"{label} is enabled for governed intraday paper validation only"
        )

    selected = max(
        (item for item in timeframes if item.get("route_status") == "READY"),
        key=_candidate_rank,
        default=None,
    )
    if selected is None:
        first_reason = next(
            (item.get("route_reason") for item in timeframes if item.get("route_reason")),
            None,
        )
        blocked_reasons.append(
            first_reason or f"{label} has no confirmed entry location"
        )

    side = (selected or {}).get("route_side")
    confidence = abs(_number((selected or {}).get("score")))
    trade_plan = _adaptive_trade_plan(
        core_payload,
        selected,
        side,
        confidence,
        execution_profile,
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
            "regime_route": execution_profile,
        },
        "trigger": {
            "status": "READY" if ready else "WAIT",
            "side": side,
            "entry_timeframe": (selected or {}).get("timeframe"),
            "reason": (
                f"{label} location and spot confirmation are ready"
                if ready
                else blocked_reasons[0]
                if blocked_reasons
                else f"{label} trade plan is invalid"
            ),
            "conditions": (selected or {}).get("route_conditions") or [],
            "execution_profile": execution_profile,
        },
        "trade_plan": trade_plan,
        "trade_plan_validation": validation,
        "data_generation_id": (
            (market_participation or {}).get("data_generation_id")
            or core_payload.get("data_generation_id")
        ),
    }


def _location_timeframe(core, spot, *, execution_profile, allowed_regimes):
    component_map = core.get("component_scores") or {}
    regime_component = component_map.get("regime") or {}
    regime = str(regime_component.get("value") or "UNKNOWN").upper()
    expected_side = allowed_regimes.get(regime)
    regime_score = _number(regime_component.get("score"))
    # Pullback and range-reversion entries intentionally occur while the
    # short-term feature trend can still point against the routed trade.  The
    # route direction therefore comes from the governed regime component;
    # spot CVD, EMA and boundary rejection below confirm that the countertrend
    # move has actually turned.  Reusing the generic feature+regime sum here
    # cancels valid BEAR_RALLY/RANGE_DISTRIBUTION shorts (and the inverse long
    # cases) before those purpose-built confirmations can be evaluated.
    strategy_score = _clamp(regime_score / 25.0 * 100, -100, 100)
    score_side = _side(strategy_score)
    atr = _optional_number(core.get("atr"))
    price = _optional_number((spot or {}).get("spot_price"))
    ema20 = _optional_number((spot or {}).get("ema20"))
    cvd = _optional_number((spot or {}).get("spot_cvd_percent"))
    zone_name = "support" if expected_side == "LONG" else "resistance"
    zone = (spot or {}).get(zone_name) or {}
    structure_level = _optional_number(
        zone.get("lower") if expected_side == "LONG" else zone.get("upper")
    )
    distance_percent = abs(_number(zone.get("distance_percent")))
    atr_percent = atr / price * 100 if atr and price else 0.0
    proximity_limit = max(0.75, min(2.5, atr_percent * 1.25))
    fresh = bool(
        core.get("status") == "OK"
        and not (core.get("freshness") or {}).get("is_stale", True)
        and not ((core.get("inputs") or {}).get("feature") or {}).get("is_stale", True)
        and not ((core.get("inputs") or {}).get("regime") or {}).get("is_stale", True)
        and (spot or {}).get("status") == "READY"
    )
    directional_spot = bool(
        cvd is not None
        and ((expected_side == "LONG" and cvd > 0) or (expected_side == "SHORT" and cvd < 0))
    )
    ema_confirmed = bool(
        price is not None
        and ema20 is not None
        and (
            (expected_side == "LONG" and price >= ema20)
            or (expected_side == "SHORT" and price <= ema20)
        )
    )
    zone_confirmed = bool(
        structure_level is not None
        and int(zone.get("tests") or 0) >= 2
        and distance_percent <= proximity_limit
        and bool(zone.get("latest_rejected"))
    )
    regime_allowed = expected_side is not None
    score_aligned = score_side == expected_side
    atr_ready = atr is not None and atr > 0
    conditions = [
        {"name": "fresh_evidence", "passed": fresh},
        {"name": "route_regime", "passed": regime_allowed},
        {"name": "score_direction", "passed": score_aligned},
        {"name": "spot_cvd", "passed": directional_spot},
        {"name": "ema_reclaim_or_rejection", "passed": ema_confirmed},
        {"name": "tested_boundary_rejection", "passed": zone_confirmed},
        {"name": "fresh_atr", "passed": atr_ready},
    ]
    ready = all(item["passed"] for item in conditions)
    reason = None
    if not fresh:
        reason = "Fresh core and spot evidence is required"
    elif not regime_allowed:
        reason = _route_wait_reason(regime, execution_profile)
    elif not score_aligned:
        reason = "Regime score does not confirm the routed direction"
    elif not directional_spot:
        reason = "Spot CVD does not confirm the routed direction"
    elif not ema_confirmed:
        reason = "Price has not confirmed the EMA reclaim or rejection"
    elif not zone_confirmed:
        reason = "Price is not at a tested support/resistance rejection boundary"
    elif not atr_ready:
        reason = "Fresh ATR is required for volatility-aware risk"
    return {
        **core,
        "spot_evidence": spot or {},
        "score": round(strategy_score, 2),
        "confidence": round(abs(strategy_score), 2),
        "signal": expected_side if ready else "WAIT",
        "bias": _direction(strategy_score),
        "regime": regime,
        "regime_route": execution_profile if regime_allowed else "WAIT",
        "route_side": expected_side if ready else None,
        "route_status": "READY" if ready else "WAIT",
        "route_reason": reason,
        "route_conditions": conditions,
        "entry_location": {
            "zone": zone_name if expected_side else None,
            "structure_level": structure_level,
            "distance_percent": distance_percent if zone else None,
            "proximity_limit_percent": round(proximity_limit, 4),
            "tests": zone.get("tests"),
            "rejection_confirmed": bool(zone.get("latest_rejected")),
        },
        "atr": atr,
    }


def _adaptive_trade_plan(
    core_payload,
    selected,
    side,
    confidence,
    execution_profile,
):
    if selected is None or side is None:
        return None
    price = _number(
        (selected.get("spot_evidence") or {}).get("spot_price")
        or selected.get("current_price")
    )
    atr = _optional_number(selected.get("atr"))
    structure_level = _optional_number(
        (selected.get("entry_location") or {}).get("structure_level")
    )
    if price <= 0 or atr is None or atr <= 0 or structure_level is None:
        return None
    return build_trade_plan(
        side,
        price,
        atr=atr,
        confidence=confidence,
        symbol=core_payload["symbol"],
        timeframe=selected.get("timeframe"),
        execution_profile=execution_profile,
        structure_level=structure_level,
    )


def _route_wait_reason(regime, execution_profile):
    if regime in {"RANGE_NEUTRAL", "LOW_VOLATILITY_COMPRESSION", "MANIPULATION_PHASE"}:
        return f"{regime} is a WAIT regime"
    if execution_profile == "TREND_PULLBACK" and regime in {
        "TRENDING_BULL",
        "TRENDING_BEAR",
    }:
        return "Trend is extended; wait for a pullback or rally entry"
    return f"{regime} is not routed to {execution_profile}"


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
