BULLISH_BIASES = {"LONG", "WEAK_LONG"}
BEARISH_BIASES = {"SHORT", "WEAK_SHORT"}


def combine_timeframe_signals(timeframes):
    lower, middle, higher = _required_timeframes(timeframes)

    if _has_no_data(timeframes):
        return {
            "overall_bias": "NO_DATA",
            "trade_permission": "BLOCKED",
            "reason": "One or more required timeframes have no signal data",
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
        }

    if _is_bearish(higher_bias) and _is_bullish(lower_bias):
        return {
            "overall_bias": "BEARISH_PULLBACK",
            "trade_permission": "SHORT_ONLY",
            "reason": f"{higher_label} is bearish while {lower_label} is bouncing",
        }

    if all(_is_bullish(item["bias"]) for item in [lower, middle, higher]):
        return {
            "overall_bias": "BULLISH_ALIGNMENT",
            "trade_permission": "LONG_ALLOWED",
            "reason": f"{lower_label}, {middle_label}, and {higher_label} are bullish",
        }

    if all(_is_bearish(item["bias"]) for item in [lower, middle, higher]):
        return {
            "overall_bias": "BEARISH_ALIGNMENT",
            "trade_permission": "SHORT_ALLOWED",
            "reason": f"{lower_label}, {middle_label}, and {higher_label} are bearish",
        }

    if _is_bullish(higher_bias) and (
        _is_bullish(middle_bias) or _is_bullish(lower_bias)
    ):
        return {
            "overall_bias": "BULLISH_CONTINUATION",
            "trade_permission": "LONG_ALLOWED",
            "reason": "Higher timeframe is bullish with lower timeframe support",
        }

    if _is_bearish(higher_bias) and (
        _is_bearish(middle_bias) or _is_bearish(lower_bias)
    ):
        return {
            "overall_bias": "BEARISH_CONTINUATION",
            "trade_permission": "SHORT_ALLOWED",
            "reason": "Higher timeframe is bearish with lower timeframe support",
        }

    return {
        "overall_bias": "MIXED",
        "trade_permission": "WAIT",
        "reason": "Timeframes are mixed or neutral",
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
