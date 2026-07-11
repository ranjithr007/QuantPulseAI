
def _get_value(obj, *names):
    for name in names:
        value = getattr(obj, name, None)
        if value is not None:
            return value
    return None


def generate_master_signal(feature, regime, orderflow, smc):

    components = score_master_signal_components(feature, regime, orderflow, smc)
    score = round(_clamp(sum(component["score"] for component in components.values()), -100, 100), 2)
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
        "confidence": round(min(100, abs(score)), 2),
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
        final_score = _number(_get_value(feature, "FinalScore", "final_score"), 50)
        trend_score = _number(_get_value(feature, "TrendScore", "trend_score"), 50)
        liquidity_score = _number(_get_value(feature, "LiquidityScore", "liquidity_score"), 50)
        feature_strength = _centered_average(final_score, trend_score, liquidity_score)

        if trend == "BULLISH":

            components["feature"]["score"] = round(12 + feature_strength * 0.24, 2)
            components["feature"]["reason"] = "Feature trend bullish"

        elif trend == "BEARISH":

            components["feature"]["score"] = round(-12 + feature_strength * 0.24, 2)
            components["feature"]["reason"] = "Feature trend bearish"

        else:
            components["feature"]["score"] = round(feature_strength * 0.12, 2)
            if components["feature"]["score"] > 0:
                components["feature"]["reason"] = "Feature strength mildly bullish"
            elif components["feature"]["score"] < 0:
                components["feature"]["reason"] = "Feature strength mildly bearish"

    # =====================
    # Regime Engine
    # =====================

    if regime:

        state = _get_value(regime, "Regime", "regime")
        components["regime"]["value"] = state
        regime_confidence = _number(_get_value(regime, "Confidence", "confidence"), 50)
        regime_strength = _centered(regime_confidence)

        if state in {
            "TRENDING_BULL",
            "BULL_PULLBACK",
            "RANGE_ACCUMULATION",
            "HIGH_VOLATILITY_BREAKOUT",
            "LIQUIDITY_GRAB_BULLISH",
        }:

            components["regime"]["score"] = round(15 + regime_strength * 0.20, 2)
            components["regime"]["reason"] = "Bull regime"

        elif state in {
            "TRENDING_BEAR",
            "BEAR_RALLY",
            "RANGE_DISTRIBUTION",
            "HIGH_VOLATILITY_BREAKDOWN",
            "LIQUIDITY_GRAB_BEARISH",
        }:

            components["regime"]["score"] = round(-15 + regime_strength * 0.20, 2)
            components["regime"]["reason"] = "Bear regime"

        else:
            components["regime"]["score"] = round(regime_strength * 0.10, 2)
            if components["regime"]["score"] > 0:
                components["regime"]["reason"] = "Regime stability mildly bullish"
            elif components["regime"]["score"] < 0:
                components["regime"]["reason"] = "Regime stability mildly bearish"

    # =====================
    # Order Flow
    # =====================

    if orderflow:

        flow = _get_value(orderflow, "FlowSignal", "flow_signal")
        components["orderflow"]["value"] = flow
        flow_confidence = _number(_get_value(orderflow, "Confidence", "confidence"), 50)
        buyer_strength = _number(_get_value(orderflow, "BuyerStrength", "buyer_strength"), 50)
        seller_strength = _number(_get_value(orderflow, "SellerStrength", "seller_strength"), 50)
        flow_strength = _centered_average(flow_confidence, 50 + (buyer_strength - seller_strength) / 2)

        if flow == "BUYERS_CONTROL":

            components["orderflow"]["score"] = round(14 + flow_strength * 0.22, 2)
            components["orderflow"]["reason"] = "Buyers control flow"

        elif flow == "SELLERS_CONTROL":

            components["orderflow"]["score"] = round(-14 + flow_strength * 0.22, 2)
            components["orderflow"]["reason"] = "Sellers control flow"

        elif flow == "POSSIBLE_BUY_REVERSAL":

            components["orderflow"]["score"] = round(8 + flow_strength * 0.18, 2)
            components["orderflow"]["reason"] = "Buyer absorption hints at reversal"

        elif flow == "POSSIBLE_SELL_REVERSAL":

            components["orderflow"]["score"] = round(-8 + flow_strength * 0.18, 2)
            components["orderflow"]["reason"] = "Seller absorption hints at reversal"

        else:
            delta = _get_value(orderflow, "Delta", "delta", "CVD", "cumulative_delta")
            if delta is not None:
                try:
                    delta = float(delta)
                except (TypeError, ValueError):
                    delta = 0

                if delta > 0:
                    components["orderflow"]["score"] = round(4 + flow_strength * 0.14, 2)
                    components["orderflow"]["reason"] = "Positive orderflow delta"
                elif delta < 0:
                    components["orderflow"]["score"] = round(-4 + flow_strength * 0.14, 2)
                    components["orderflow"]["reason"] = "Negative orderflow delta"

    # =====================
    # SMC
    # =====================

    if smc:

        bias = _get_value(smc, "smc_bias", "bias")
        components["smc"]["value"] = bias
        smc_confidence = _number(_get_value(smc, "confidence", "Confidence"), 50)
        smc_strength = _centered(smc_confidence)

        if bias == "LONG":

            components["smc"]["score"] = round(16 + smc_strength * 0.24, 2)
            components["smc"]["reason"] = "SMC bullish"

        elif bias == "SHORT":

            components["smc"]["score"] = round(-16 + smc_strength * 0.24, 2)
            components["smc"]["reason"] = "SMC bearish"

        else:
            structure = _get_value(smc, "structure", "bos_type", "choch_type")
            text = str(structure or "").upper()
            if "BULL" in text or "LONG" in text:
                components["smc"]["score"] = round(8 + smc_strength * 0.18, 2)
                components["smc"]["reason"] = "Bullish SMC structure"
            elif "BEAR" in text or "SHORT" in text:
                components["smc"]["score"] = round(-8 + smc_strength * 0.18, 2)
                components["smc"]["reason"] = "Bearish SMC structure"

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


def _number(value, fallback=0):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(fallback)
    return number


def _clamp(value, minimum, maximum):
    return max(minimum, min(maximum, float(value)))


def _centered(value):
    return _clamp(_number(value, 50) - 50, -50, 50)


def _centered_average(*values):
    valid = [_number(value, 50) for value in values if value is not None]
    if not valid:
        return 0.0
    average = sum(valid) / len(valid)
    return _centered(average)
