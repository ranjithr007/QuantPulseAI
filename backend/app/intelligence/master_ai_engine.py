
def _get_value(obj, *names):
    for name in names:
        value = getattr(obj, name, None)
        if value is not None:
            return value
    return None


def generate_master_signal(feature, regime, orderflow, smc):

    components = score_master_signal_components(feature, regime, orderflow, smc)
    score = sum(component["score"] for component in components.values())
    reasons = [
        component["reason"]
        for component in components.values()
        if component["reason"]
    ]

    signal = _signal_from_score(score)
    bias = _bias_from_score(score, signal)

    return {
        "signal": signal,
        "bias": bias,
        "confidence": abs(score),
        "score": score,
        "reasons": reasons,
        "scoring_profile": build_scoring_profile(components, score=score, signal=signal, bias=bias),
    }


def score_master_signal_components(feature, regime, orderflow, smc):
    components = {
        "feature": {"score": 0, "reason": None, "value": None},
        "regime": {"score": 0, "reason": None, "value": None},
        "orderflow": {"score": 0, "reason": None, "value": None},
        "smc": {"score": 0, "reason": None, "value": None},
    }

    # =====================
    # Feature Factory
    # =====================

    if feature:

        trend = _get_value(feature, "Trend", "trend")
        components["feature"]["value"] = trend

        if trend == "BULLISH":

            components["feature"]["score"] = 20
            components["feature"]["reason"] = "Feature trend bullish"

        elif trend == "BEARISH":

            components["feature"]["score"] = -20
            components["feature"]["reason"] = "Feature trend bearish"

    # =====================
    # Regime Engine
    # =====================

    if regime:

        state = _get_value(regime, "Regime", "regime")
        components["regime"]["value"] = state

        if state in {
            "TRENDING_BULL",
            "BULL_PULLBACK",
            "RANGE_ACCUMULATION",
            "HIGH_VOLATILITY_BREAKOUT",
            "LIQUIDITY_GRAB_BULLISH",
        }:

            components["regime"]["score"] = 25
            components["regime"]["reason"] = "Bull regime"

        elif state in {
            "TRENDING_BEAR",
            "BEAR_RALLY",
            "RANGE_DISTRIBUTION",
            "HIGH_VOLATILITY_BREAKDOWN",
            "LIQUIDITY_GRAB_BEARISH",
        }:

            components["regime"]["score"] = -25
            components["regime"]["reason"] = "Bear regime"

    # =====================
    # Order Flow
    # =====================

    if orderflow:

        flow = _get_value(orderflow, "FlowSignal", "flow_signal")
        components["orderflow"]["value"] = flow

        if flow == "BUYERS_CONTROL":

            components["orderflow"]["score"] = 25
            components["orderflow"]["reason"] = "Buyers control flow"

        elif flow == "SELLERS_CONTROL":

            components["orderflow"]["score"] = -25
            components["orderflow"]["reason"] = "Sellers control flow"

    # =====================
    # SMC
    # =====================

    if smc:

        bias = getattr(smc, "smc_bias", None)
        components["smc"]["value"] = bias

        if bias == "LONG":

            components["smc"]["score"] = 30
            components["smc"]["reason"] = "SMC bullish"

        elif bias == "SHORT":

            components["smc"]["score"] = -30
            components["smc"]["reason"] = "SMC bearish"

    return components


def build_scoring_profile(components, *, score, signal, bias):
    base_weights = {
        "feature": 20,
        "regime": 25,
        "orderflow": 25,
        "smc": 30,
    }
    component_entries = []
    absolute_total = sum(abs(component.get("score", 0) or 0) for component in components.values())

    for name, component in components.items():
        component_score = float(component.get("score", 0) or 0)
        normalized_weight = round(
            abs(component_score) / absolute_total,
            4,
        ) if absolute_total else 0.0
        component_entries.append(
            {
                "name": name,
                "value": component.get("value"),
                "reason": component.get("reason"),
                "score": component_score,
                "base_weight": base_weights.get(name, 0),
                "normalized_weight": normalized_weight,
                "direction": "positive" if component_score > 0 else "negative" if component_score < 0 else "neutral",
            }
        )

    return {
        "source": "governed_master_ai_scoring",
        "score_range": {"min": -100, "max": 100},
        "signal_threshold": 40,
        "bias_threshold": 15,
        "base_weights": base_weights,
        "active_total_weight": absolute_total,
        "score": score,
        "signal": signal,
        "bias": bias,
        "components": component_entries,
    }


def _signal_from_score(score):
    if score >= 40:
        return "LONG"

    if score <= -40:
        return "SHORT"

    return "WAIT"


def _bias_from_score(score, signal):
    if signal == "LONG":
        return "LONG"

    if signal == "SHORT":
        return "SHORT"

    if score >= 15:
        return "WEAK_LONG"

    if score <= -15:
        return "WEAK_SHORT"

    return "NEUTRAL"
