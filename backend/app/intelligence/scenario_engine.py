BULLISH_BIASES = {"LONG", "WEAK_LONG"}
BEARISH_BIASES = {"SHORT", "WEAK_SHORT"}
NEUTRAL_BIASES = {"NEUTRAL"}

SCENARIO_NAMES = (
    "BULLISH_CONTINUATION",
    "BEARISH_CONTINUATION",
    "RANGE_ROTATION",
    "INVALIDATION",
)


def build_scenario_plan(confirmation, timeframes, trade_plan=None, current_price=None, atr=None):
    lower, middle, higher = _required_timeframes(timeframes)
    current_price = _resolve_price(current_price, lower, middle, higher)
    atr = _resolve_atr(atr, trade_plan, current_price)
    context = _context_summary(confirmation, timeframes)
    weights = _initial_weights(confirmation, context)
    probabilities = _normalize_weights(weights)

    paths = [
        _path_bullish(probabilities["BULLISH_CONTINUATION"], current_price, atr, confirmation, context),
        _path_bearish(probabilities["BEARISH_CONTINUATION"], current_price, atr, confirmation, context),
        _path_range(probabilities["RANGE_ROTATION"], current_price, atr, confirmation, context),
        _path_invalidation(probabilities["INVALIDATION"], current_price, atr, confirmation, context),
    ]
    primary = max(paths, key=lambda item: item["probability"])

    return {
        "source": "scenario_engine",
        "overall_bias": confirmation.get("overall_bias"),
        "trade_permission": confirmation.get("trade_permission"),
        "scenario_type": primary["name"],
        "confidence": primary["confidence"],
        "reason": primary["reason"],
        "paths": paths,
        "primary_path": primary,
        "market_context": context,
        "price_context": {
            "current_price": current_price,
            "atr": atr,
            "timeframes_used": [item["timeframe"] for item in timeframes],
        },
        "trade_plan": _trade_plan_snapshot(trade_plan),
    }


def _initial_weights(confirmation, context):
    weights = {
        "BULLISH_CONTINUATION": 25,
        "BEARISH_CONTINUATION": 25,
        "RANGE_ROTATION": 25,
        "INVALIDATION": 25,
    }

    overall_bias = confirmation.get("overall_bias")
    trade_permission = confirmation.get("trade_permission")
    bull_support = context["bull_support"]
    bear_support = context["bear_support"]
    neutral_support = context["neutral_support"]
    stale_count = context["stale_count"]
    no_data_count = context["no_data_count"]
    mixed_support = min(bull_support, bear_support)

    if overall_bias in {"BULLISH_PULLBACK", "BULLISH_CONTINUATION", "BULLISH_ALIGNMENT"}:
        weights["BULLISH_CONTINUATION"] += 15
        weights["RANGE_ROTATION"] += 5
        weights["BEARISH_CONTINUATION"] -= 5
    elif overall_bias in {"BEARISH_PULLBACK", "BEARISH_CONTINUATION", "BEARISH_ALIGNMENT"}:
        weights["BEARISH_CONTINUATION"] += 15
        weights["RANGE_ROTATION"] += 5
        weights["BULLISH_CONTINUATION"] -= 5
    elif overall_bias == "MIXED":
        weights["RANGE_ROTATION"] += 15
        weights["INVALIDATION"] += 5
    elif overall_bias == "NO_DATA":
        weights["INVALIDATION"] += 20

    if trade_permission in {"LONG_ALLOWED", "LONG_ONLY"}:
        weights["BULLISH_CONTINUATION"] += 10
    if trade_permission in {"SHORT_ALLOWED", "SHORT_ONLY"}:
        weights["BEARISH_CONTINUATION"] += 10
    if trade_permission == "WAIT":
        weights["RANGE_ROTATION"] += 8

    weights["BULLISH_CONTINUATION"] += bull_support * 7 + context["fresh_count"] * 2 - bear_support * 3
    weights["BEARISH_CONTINUATION"] += bear_support * 7 + context["fresh_count"] * 2 - bull_support * 3
    weights["RANGE_ROTATION"] += neutral_support * 8 + mixed_support * 4
    weights["INVALIDATION"] += stale_count * 12 + no_data_count * 15

    return weights


def _normalize_weights(weights):
    sanitized = {name: max(1, int(round(value))) for name, value in weights.items()}
    total = sum(sanitized.values())
    target_total = 100

    scaled = {
        name: int(round((value / total) * target_total))
        for name, value in sanitized.items()
    }
    scaled_total = sum(scaled.values())

    if scaled_total != target_total:
        remainder = target_total - scaled_total
        ordered = sorted(sanitized.items(), key=lambda item: item[1], reverse=True)

        for index in range(abs(remainder)):
            name = ordered[index % len(ordered)][0]
            scaled[name] += 1 if remainder > 0 else -1

    for name in SCENARIO_NAMES:
        scaled.setdefault(name, 1)

    return scaled


def _path_bullish(probability, current_price, atr, confirmation, context):
    return {
        "name": "BULLISH_CONTINUATION",
        "direction": "LONG",
        "probability": probability,
        "confidence": probability,
        "trigger": "Bullish structure and lower-timeframe stabilization continue",
        "target_price": round(current_price + (atr * 2), 8),
        "invalidation_price": round(current_price - atr, 8),
        "reason": "Bullish continuation is favored by the higher-timeframe context",
        "notes": _notes(
            confirmation,
            context,
            "Higher timeframe holds and pullback resolves upward",
        ),
    }


def _path_bearish(probability, current_price, atr, confirmation, context):
    return {
        "name": "BEARISH_CONTINUATION",
        "direction": "SHORT",
        "probability": probability,
        "confidence": probability,
        "trigger": "Bearish structure and lower-timeframe rejection continue",
        "target_price": round(current_price - (atr * 2), 8),
        "invalidation_price": round(current_price + atr, 8),
        "reason": "Bearish continuation is favored by the higher-timeframe context",
        "notes": _notes(
            confirmation,
            context,
            "Higher timeframe holds and bounce resolves downward",
        ),
    }


def _path_range(probability, current_price, atr, confirmation, context):
    return {
        "name": "RANGE_ROTATION",
        "direction": "WAIT",
        "probability": probability,
        "confidence": probability,
        "trigger": "Price rotates between local range extremes",
        "target_price": round(current_price + atr, 8),
        "secondary_target_price": round(current_price - atr, 8),
        "invalidation_price": round(current_price + (atr * 1.5), 8),
        "reason": "Range rotation is the most balanced expectation",
        "notes": _notes(
            confirmation,
            context,
            "Mixed timeframes or neutral pressure favor rotation over trend",
        ),
    }


def _path_invalidation(probability, current_price, atr, confirmation, context):
    return {
        "name": "INVALIDATION",
        "direction": "WAIT",
        "probability": probability,
        "confidence": probability,
        "trigger": "Freshness loss or strong contradiction invalidates the setup",
        "target_price": None,
        "invalidation_price": round(current_price - (atr * 1.5), 8),
        "reason": "The setup should be reassessed before any directional bias",
        "notes": _notes(
            confirmation,
            context,
            "The setup is no longer dependable and should be reassessed",
        ),
    }


def _notes(confirmation, context, message):
    notes = [message]

    if confirmation.get("reason"):
        notes.append(confirmation["reason"])

    if context["stale_count"]:
        notes.append(f"{context['stale_count']} timeframe(s) are stale")

    if context["no_data_count"]:
        notes.append(f"{context['no_data_count']} timeframe(s) have no data")

    return notes


def _context_summary(confirmation, timeframes):
    bull_support = 0
    bear_support = 0
    neutral_support = 0
    stale_count = 0
    no_data_count = 0
    fresh_count = 0

    for item in timeframes:
        bias = item.get("bias")
        signal = item.get("signal")
        freshness = item.get("freshness", {})

        if bias in BULLISH_BIASES:
            bull_support += 1
        elif bias in BEARISH_BIASES:
            bear_support += 1
        elif bias in NEUTRAL_BIASES:
            neutral_support += 1

        if signal == "NO_DATA":
            no_data_count += 1
        elif freshness.get("is_stale", True):
            stale_count += 1
        else:
            fresh_count += 1

    return {
        "bull_support": bull_support,
        "bear_support": bear_support,
        "neutral_support": neutral_support,
        "stale_count": stale_count,
        "no_data_count": no_data_count,
        "fresh_count": fresh_count,
        "overall_bias": confirmation.get("overall_bias"),
        "trade_permission": confirmation.get("trade_permission"),
    }


def _resolve_price(current_price, lower, middle, higher):
    if current_price is not None:
        return float(current_price)

    for item in (lower, middle, higher):
        price = item.get("current_price")
        if price is not None:
            return float(price)

    return 0.0


def _resolve_atr(atr, trade_plan, current_price):
    if atr is not None and atr > 0:
        return float(atr)

    if trade_plan:
        plan_atr = trade_plan.get("atr")
        if plan_atr is not None and plan_atr > 0:
            return float(plan_atr)

    if current_price:
        return float(current_price) * 0.01

    return 1.0


def _trade_plan_snapshot(trade_plan):
    if not trade_plan:
        return None

    return {
        "entry": trade_plan.get("entry"),
        "stop_loss": trade_plan.get("stop_loss"),
        "target1": trade_plan.get("target1"),
        "target2": trade_plan.get("target2"),
        "atr": trade_plan.get("atr"),
        "risk_reward": trade_plan.get("risk_reward"),
    }


def _required_timeframes(timeframes):
    if len(timeframes) < 3:
        raise ValueError("At least three timeframes are required")

    return timeframes[0], timeframes[len(timeframes) // 2], timeframes[-1]
