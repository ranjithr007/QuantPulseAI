"""Independent spot-led market participation trend.

This engine does not replace the existing timeframe regime.  It answers a
different question: is genuine spot participation supporting the proposed
futures direction?
"""

from math import isfinite
from statistics import median


TIMEFRAME_WEIGHTS = {"1h": 0.15, "2h": 0.20, "4h": 0.25, "1d": 0.40}
EXECUTION_THRESHOLD = 40.0
MINIMUM_BARS = 25


def analyze_spot_stack(symbol, candles_by_timeframe):
    timeframes = []
    for timeframe in TIMEFRAME_WEIGHTS:
        timeframes.append(
            analyze_spot_timeframe(
                symbol,
                timeframe,
                (candles_by_timeframe or {}).get(timeframe) or [],
            )
        )
    ready = [item for item in timeframes if item["status"] == "READY"]
    weighted_score = sum(
        item["score"] * TIMEFRAME_WEIGHTS[item["timeframe"]]
        for item in ready
    )
    weight = sum(TIMEFRAME_WEIGHTS[item["timeframe"]] for item in ready)
    score = weighted_score / weight if weight else 0.0
    return {
        "symbol": str(symbol).upper(),
        "status": "READY" if len(ready) == len(TIMEFRAME_WEIGHTS) else "DEGRADED",
        "score": round(_clamp(score, -100, 100), 2),
        "timeframes": timeframes,
        "missing_timeframes": [
            item["timeframe"] for item in timeframes if item["status"] != "READY"
        ],
    }


def analyze_spot_timeframe(symbol, timeframe, candles):
    bars = [item for item in candles if item.get("is_final", True)]
    if len(bars) < MINIMUM_BARS:
        return {
            "symbol": str(symbol).upper(),
            "timeframe": timeframe,
            "status": "INSUFFICIENT_SPOT_HISTORY",
            "score": 0.0,
            "direction": "NEUTRAL",
            "bar_count": len(bars),
            "required_bar_count": MINIMUM_BARS,
        }

    recent = bars[-20:]
    latest = recent[-1]
    previous_volumes = [
        _number(item.get("quote_volume")) for item in recent[:-1]
        if _number(item.get("quote_volume")) > 0
    ]
    normal_volume = median(previous_volumes) if previous_volumes else 0.0
    relative_volume = (
        _number(latest.get("quote_volume")) / normal_volume
        if normal_volume > 0
        else 0.0
    )
    spot_delta = sum(_number(item.get("spot_delta_quote")) for item in recent)
    quote_volume = sum(_number(item.get("quote_volume")) for item in recent)
    cvd_percent = (spot_delta / quote_volume) * 100 if quote_volume > 0 else 0.0
    first_open = _number(recent[0].get("open"))
    last_close = _number(latest.get("close"))
    price_change_percent = (
        ((last_close - first_open) / first_open) * 100 if first_open > 0 else 0.0
    )
    ema20 = _ema([_number(item.get("close")) for item in recent], 20)
    score = 0.0
    reasons = []

    if last_close > ema20:
        score += 12
        reasons.append("Spot price is above its 20-period EMA")
    elif last_close < ema20:
        score -= 12
        reasons.append("Spot price is below its 20-period EMA")

    cvd_score = _clamp(cvd_percent * 1.8, -22, 22)
    score += cvd_score
    if cvd_score > 0:
        reasons.append("Genuine spot taker CVD is positive")
    elif cvd_score < 0:
        reasons.append("Genuine spot taker CVD is negative")

    price_score = _clamp(price_change_percent * 2.5, -12, 12)
    score += price_score
    if relative_volume >= 1.2:
        volume_direction = 1 if spot_delta > 0 else -1 if spot_delta < 0 else 0
        score += volume_direction * min(10, relative_volume * 4)
        reasons.append(
            "Spot volume expansion confirms buying"
            if volume_direction > 0
            else "Spot volume expansion confirms selling"
            if volume_direction < 0
            else "Spot volume expanded without directional taker control"
        )

    zones = find_dynamic_price_zones(bars)
    resistance = zones.get("resistance")
    support = zones.get("support")
    if resistance:
        if resistance["breakout_accepted"]:
            score += 12
            reasons.append("Spot price accepted above dynamic resistance")
        elif resistance["latest_rejected"]:
            score -= 12
            reasons.append("Spot price was rejected from dynamic resistance")
    if support:
        if support["breakdown_accepted"]:
            score -= 12
            reasons.append("Spot price accepted below dynamic support")
        elif support["latest_rejected"]:
            score += 12
            reasons.append("Spot buyers defended dynamic support")

    score = round(_clamp(score, -100, 100), 2)
    return {
        "symbol": str(symbol).upper(),
        "timeframe": timeframe,
        "status": "READY",
        "score": score,
        "direction": _direction(score, neutral_band=15),
        "bar_count": len(bars),
        "source_timestamp": latest.get("close_time"),
        "spot_price": last_close,
        "ema20": round(ema20, 8),
        "price_change_percent": round(price_change_percent, 4),
        "spot_cvd_quote": round(spot_delta, 2),
        "spot_cvd_percent": round(cvd_percent, 4),
        "relative_spot_volume": round(relative_volume, 4),
        "spot_quote_volume": round(quote_volume, 2),
        "resistance": resistance,
        "support": support,
        "reasons": reasons,
    }


def build_market_participation_trend(
    spot_stack,
    *,
    derivatives=None,
    breadth=None,
    ethbtc=None,
    liquidation=None,
    external_context=None,
):
    base_score = _number((spot_stack or {}).get("score"))
    score = base_score
    reasons = []
    components = {
        "spot_stack": round(base_score, 2),
        "derivatives": 0.0,
        "market_breadth": 0.0,
        "ethbtc": 0.0,
        "liquidation": 0.0,
        "external_context": 0.0,
    }

    derivative_score, derivative_reasons = _derivative_component(
        derivatives,
        base_score,
    )
    score += derivative_score
    components["derivatives"] = derivative_score
    reasons.extend(derivative_reasons)

    breadth_score = _breadth_component(breadth)
    score += breadth_score
    components["market_breadth"] = breadth_score
    if breadth_score:
        reasons.append(
            "Broad crypto participation is improving"
            if breadth_score > 0
            else "Broad crypto participation is weak"
        )

    ethbtc_score = _ethbtc_component(ethbtc)
    score += ethbtc_score
    components["ethbtc"] = ethbtc_score
    if ethbtc_score:
        reasons.append(
            "ETH/BTC participation is stabilising"
            if ethbtc_score > 0
            else "ETH/BTC participation is weakening"
        )

    liquidation_score = _liquidation_component(liquidation)
    score += liquidation_score
    components["liquidation"] = liquidation_score
    if liquidation_score:
        reasons.append(
            "Liquidation pressure favours upside"
            if liquidation_score > 0
            else "Long-liquidation pressure is below the market"
        )

    external_score, external_status = _external_component(external_context)
    score += external_score
    components["external_context"] = external_score
    score = round(_clamp(score, -100, 100), 2)
    quality_state = (
        "OK" if (spot_stack or {}).get("status") == "READY" else "DEGRADED"
    )
    direction = _direction(score, neutral_band=EXECUTION_THRESHOLD)
    return {
        "source": "market_participation_trend_v1",
        "symbol": (spot_stack or {}).get("symbol"),
        "status": "READY" if quality_state == "OK" else "DEGRADED",
        "quality_state": quality_state,
        "direction": direction,
        "execution_side": (
            "LONG" if direction == "BULLISH" else "SHORT" if direction == "BEARISH" else None
        ),
        "score": score,
        "confidence": round(abs(score), 2),
        "execution_threshold": EXECUTION_THRESHOLD,
        "components": components,
        "spot": spot_stack,
        "derivatives": derivatives or {},
        "breadth": breadth or {},
        "ethbtc": ethbtc or {},
        "liquidation": liquidation or {},
        "external_context": {
            "status": external_status,
            "score": external_score,
            "inputs": external_context or {},
            "policy": "ADVISORY_ONLY_UNTIL_VERIFIED_PROVIDER",
        },
        "reasons": [
            *((spot_stack or {}).get("timeframes", [{}])[0].get("reasons") or []),
            *reasons,
        ],
    }


def build_market_breadth(spot_stacks):
    rows = []
    for symbol, stack in sorted((spot_stacks or {}).items()):
        one_hour = next(
            (
                item
                for item in stack.get("timeframes") or []
                if item.get("timeframe") == "1h" and item.get("status") == "READY"
            ),
            None,
        )
        if one_hour:
            rows.append({"symbol": symbol, "score": one_hour["score"]})
    bullish = sum(1 for item in rows if item["score"] >= 15)
    bearish = sum(1 for item in rows if item["score"] <= -15)
    total = len(rows)
    return {
        "status": "READY" if total else "UNAVAILABLE",
        "symbol_count": total,
        "bullish_count": bullish,
        "bearish_count": bearish,
        "bullish_percent": round((bullish / total) * 100, 2) if total else 0.0,
        "bearish_percent": round((bearish / total) * 100, 2) if total else 0.0,
        "records": rows,
    }


def find_dynamic_price_zones(candles):
    bars = list(candles or [])
    if len(bars) < MINIMUM_BARS:
        return {"resistance": None, "support": None}
    reference = bars[:-2] if len(bars) > 2 else bars
    latest = bars[-1]
    closes = [_number(item.get("close")) for item in bars[-20:]]
    atr = _average_true_range(bars[-20:])
    tolerance = max(_number(latest.get("close")) * 0.005, atr * 0.5)
    swing_highs = _swings(reference, "high")
    swing_lows = _swings(reference, "low")
    resistance = _select_zone(
        swing_highs,
        _number(latest.get("close")),
        tolerance,
        above=True,
    )
    support = _select_zone(
        swing_lows,
        _number(latest.get("close")),
        tolerance,
        above=False,
    )
    if resistance:
        resistance.update(
            {
                "latest_rejected": (
                    resistance["tests"] >= 2
                    and
                    _number(latest.get("high")) >= resistance["lower"]
                    and _number(latest.get("close")) < resistance["lower"]
                ),
                "breakout_accepted": all(
                    value > resistance["upper"] for value in closes[-2:]
                ),
            }
        )
    if support:
        support.update(
            {
                "latest_rejected": (
                    support["tests"] >= 2
                    and
                    _number(latest.get("low")) <= support["upper"]
                    and _number(latest.get("close")) > support["upper"]
                ),
                "breakdown_accepted": all(
                    value < support["lower"] for value in closes[-2:]
                ),
            }
        )
    return {"resistance": resistance, "support": support}


def _swings(bars, field):
    values = []
    for index in range(2, len(bars) - 2):
        value = _number(bars[index].get(field))
        neighbours = [
            _number(bars[position].get(field))
            for position in range(index - 2, index + 3)
            if position != index
        ]
        if field == "high" and all(value >= item for item in neighbours):
            values.append(value)
        if field == "low" and all(value <= item for item in neighbours):
            values.append(value)
    return values


def _select_zone(values, current_price, tolerance, *, above):
    candidates = [
        value
        for value in values
        if (value >= current_price * 0.995 if above else value <= current_price * 1.005)
    ]
    if not candidates:
        return None
    clusters = []
    for value in sorted(candidates):
        cluster = next(
            (
                item
                for item in clusters
                if abs(value - item["center"]) <= tolerance
            ),
            None,
        )
        if cluster is None:
            clusters.append({"center": value, "values": [value]})
        else:
            cluster["values"].append(value)
            cluster["center"] = sum(cluster["values"]) / len(cluster["values"])
    chosen = min(
        clusters,
        key=lambda item: (
            abs(item["center"] - current_price),
            -len(item["values"]),
        ),
    )
    return {
        "lower": round(min(chosen["values"]) - tolerance / 2, 8),
        "upper": round(max(chosen["values"]) + tolerance / 2, 8),
        "center": round(chosen["center"], 8),
        "tests": len(chosen["values"]),
        "distance_percent": round(
            ((chosen["center"] - current_price) / current_price) * 100,
            4,
        ) if current_price else None,
    }


def _derivative_component(derivatives, base_score):
    values = derivatives or {}
    funding = _optional_number(values.get("funding_rate"))
    oi_change = _optional_number(values.get("open_interest_change_percent"))
    score = 0.0
    reasons = []
    side = 1 if base_score > 0 else -1 if base_score < 0 else 0
    if oi_change is not None:
        if oi_change > 0 and side:
            score += side * min(8, abs(oi_change) * 2)
            reasons.append("Open interest is expanding with the spot direction")
        elif oi_change < 0:
            reasons.append("Open interest is contracting")
    if funding is not None:
        if abs(funding) <= 0.0003 and side:
            score += side * 4
            reasons.append("Funding remains neutral")
        elif funding > 0.0005:
            score -= 8
            reasons.append("Positive funding indicates crowded longs")
        elif funding < -0.0005:
            score += 8
            reasons.append("Negative funding indicates crowded shorts")
    return round(_clamp(score, -15, 15), 2), reasons


def _breadth_component(breadth):
    if not breadth or breadth.get("status") != "READY":
        return 0.0
    bullish = _number(breadth.get("bullish_percent"))
    bearish = _number(breadth.get("bearish_percent"))
    return round(_clamp((bullish - bearish) * 0.15, -10, 10), 2)


def _ethbtc_component(ethbtc):
    if not ethbtc or ethbtc.get("status") != "READY":
        return 0.0
    return round(_clamp(_number(ethbtc.get("score")) * 0.15, -6, 6), 2)


def _liquidation_component(liquidation):
    if not liquidation or liquidation.get("data_quality") != "OBSERVED":
        return 0.0
    bias = str(liquidation.get("bias") or "").upper()
    if bias == "HUNT_LONGS":
        return -8.0
    if bias == "HUNT_SHORTS":
        return 8.0
    return 0.0


def _external_component(context):
    if not context or context.get("status") != "VERIFIED":
        return 0.0, "UNAVAILABLE"
    values = [
        _optional_number(context.get(name))
        for name in (
            "etf_flow_score",
            "macro_score",
            "regulatory_score",
            "corporate_flow_score",
        )
    ]
    usable = [value for value in values if value is not None]
    if not usable:
        return 0.0, "UNAVAILABLE"
    return round(_clamp(sum(usable) / len(usable), -10, 10), 2), "VERIFIED"


def _ema(values, period):
    values = [value for value in values if isfinite(value)]
    if not values:
        return 0.0
    multiplier = 2 / (period + 1)
    result = values[0]
    for value in values[1:]:
        result = (value - result) * multiplier + result
    return result


def _average_true_range(bars):
    ranges = [
        max(0.0, _number(item.get("high")) - _number(item.get("low")))
        for item in bars
    ]
    return sum(ranges) / len(ranges) if ranges else 0.0


def _direction(score, *, neutral_band):
    if score >= neutral_band:
        return "BULLISH"
    if score <= -neutral_band:
        return "BEARISH"
    return "NEUTRAL"


def _optional_number(value):
    try:
        parsed = float(value)
        return parsed if isfinite(parsed) else None
    except (TypeError, ValueError):
        return None


def _number(value):
    parsed = _optional_number(value)
    return parsed if parsed is not None else 0.0


def _clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))
