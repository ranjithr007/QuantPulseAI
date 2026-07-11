BULLISH_BIASES = {"LONG", "WEAK_LONG"}
BEARISH_BIASES = {"SHORT", "WEAK_SHORT"}
ALIGNED_BIASES = {
    "BULLISH_ALIGNMENT",
    "BEARISH_ALIGNMENT",
    "BULLISH_CONTINUATION",
    "BEARISH_CONTINUATION",
    "BULLISH_PULLBACK",
    "BEARISH_PULLBACK",
}


def combine_timeframe_signals(timeframes):
    lower, middle, higher = _required_timeframes(timeframes)

    if _has_no_data(timeframes):
        return {
            "overall_bias": "NO_DATA",
            "trade_permission": "BLOCKED",
            "reason": "One or more required timeframes have no signal data",
            "stack_state": "NO_DATA",
            "confidence_penalty": 0,
        }

    lower_bias = lower["bias"]
    middle_bias = middle["bias"]
    higher_bias = higher["bias"]
    lower_label = lower["timeframe"]
    middle_label = middle["timeframe"]
    higher_label = higher["timeframe"]

    if _is_bullish(higher_bias) and _is_bearish(lower_bias):
        return {
            "overall_bias": "BULLISH_PULLBACK",
            "trade_permission": "LONG_ONLY",
            "reason": f"{higher_label} is bullish while {lower_label} is pulling back",
            "stack_state": "ALIGNED",
            "confidence_penalty": 0,
        }

    if _is_bearish(higher_bias) and _is_bullish(lower_bias):
        return {
            "overall_bias": "BEARISH_PULLBACK",
            "trade_permission": "SHORT_ONLY",
            "reason": f"{higher_label} is bearish while {lower_label} is bouncing",
            "stack_state": "ALIGNED",
            "confidence_penalty": 0,
        }

    if all(_is_bullish(item["bias"]) for item in [lower, middle, higher]):
        return {
            "overall_bias": "BULLISH_ALIGNMENT",
            "trade_permission": "LONG_ALLOWED",
            "reason": f"{lower_label}, {middle_label}, and {higher_label} are bullish",
            "stack_state": "ALIGNED",
            "confidence_penalty": 0,
        }

    if all(_is_bearish(item["bias"]) for item in [lower, middle, higher]):
        return {
            "overall_bias": "BEARISH_ALIGNMENT",
            "trade_permission": "SHORT_ALLOWED",
            "reason": f"{lower_label}, {middle_label}, and {higher_label} are bearish",
            "stack_state": "ALIGNED",
            "confidence_penalty": 0,
        }

    if _is_bullish(higher_bias) and (
        _is_bullish(middle_bias) or _is_bullish(lower_bias)
    ):
        return {
            "overall_bias": "BULLISH_CONTINUATION",
            "trade_permission": "LONG_ALLOWED",
            "reason": "Higher timeframe is bullish with lower timeframe support",
            "stack_state": "ALIGNED",
            "confidence_penalty": 0,
        }

    if _is_bearish(higher_bias) and (
        _is_bearish(middle_bias) or _is_bearish(lower_bias)
    ):
        return {
            "overall_bias": "BEARISH_CONTINUATION",
            "trade_permission": "SHORT_ALLOWED",
            "reason": "Higher timeframe is bearish with lower timeframe support",
            "stack_state": "ALIGNED",
            "confidence_penalty": 0,
        }

    stack_state, confidence_penalty = _mixed_stack_profile(timeframes)
    return {
        "overall_bias": "MIXED",
        "trade_permission": "WAIT",
        "reason": "Timeframes are mixed or neutral",
        "stack_state": stack_state,
        "confidence_penalty": confidence_penalty,
    }


def _has_no_data(timeframes):
    return any(item.get("signal") == "NO_DATA" for item in timeframes)


def _required_timeframes(timeframes):
    if len(timeframes) != 3:
        raise ValueError("Exactly three timeframes are required")

    return timeframes[0], timeframes[1], timeframes[2]


def _is_bullish(bias):
    return bias in BULLISH_BIASES


def _is_bearish(bias):
    return bias in BEARISH_BIASES


def _mixed_stack_profile(timeframes):
    bullish_count = sum(1 for item in timeframes if _is_bullish(item.get("bias")))
    bearish_count = sum(1 for item in timeframes if _is_bearish(item.get("bias")))

    if bullish_count and bearish_count:
        return "MIXED_STRONG", 15

    if bullish_count == 2 or bearish_count == 2:
        return "MIXED_LIGHT", 5

    if bullish_count == 1 or bearish_count == 1:
        return "MIXED_LIGHT", 5

    return "MIXED_LIGHT", 5
