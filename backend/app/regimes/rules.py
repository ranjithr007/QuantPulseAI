def detect_regime(features):

    trend = features.TrendScore

    momentum = features.MomentumScore

    volatility = features.VolatilityScore

    liquidity = features.LiquidityScore

    # Bull trend

    if trend > 70 and momentum > 60:

        return {"regime": "TRENDING_BULL", "confidence": 85, "strategy": "BUY_PULLBACK"}

    # Bear trend

    if trend < 40 and momentum < 40:

        return {"regime": "TRENDING_BEAR", "confidence": 85, "strategy": "SHORT_RALLY"}

    # Manipulation

    if liquidity > 80 and volatility > 75:

        return {"regime": "MANIPULATION_PHASE", "confidence": 90, "strategy": "WAIT"}

    return {
        "regime": "RANGE_ACCUMULATION",
        "confidence": 60,
        "strategy": "WAIT_BREAKOUT",
    }