
def generate_master_signal(feature, regime, orderflow, smc):

    score = 0
    reasons = []

    # =====================
    # Feature Factory
    # =====================

    if feature:

        trend = getattr(feature, "trend", None)

        if trend == "BULLISH":

            score += 20

            reasons.append("Feature trend bullish")

        elif trend == "BEARISH":

            score -= 20

            reasons.append("Feature trend bearish")

    # =====================
    # Regime Engine
    # =====================

    if regime:

        state = getattr(regime, "regime", None)

        if state == "TRENDING_BULL":

            score += 25

            reasons.append("Bull regime")

        elif state == "TRENDING_BEAR":

            score -= 25

            reasons.append("Bear regime")

    # =====================
    # Order Flow
    # =====================

    if orderflow:

        flow = getattr(orderflow, "flow_signal", None)

        if flow == "BUYERS_CONTROL":

            score += 25

            reasons.append("Buyers control flow")

        elif flow == "SELLERS_CONTROL":

            score -= 25

            reasons.append("Sellers control flow")

    # =====================
    # SMC
    # =====================

    if smc:

        bias = getattr(smc, "smc_bias", None)

        if bias == "LONG":

            score += 30

            reasons.append("SMC bullish")

        elif bias == "SHORT":

            score -= 30

            reasons.append("SMC bearish")

    # =====================
    # Decision
    # =====================

    if score >= 40:

        signal = "LONG"

    elif score <= -40:

        signal = "SHORT"

    else:

        signal = "WAIT"

    return {
        "signal": signal,
        "confidence": abs(score),
        "score": score,
        "reasons": reasons,
    }