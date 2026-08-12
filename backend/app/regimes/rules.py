REGIME_DEFINITIONS = {
    "TRENDING_BULL": {
        "strategy": "BUY_PULLBACK",
        "bias": "BULLISH",
        "direction": "BULLISH",
        "risk_mode": "NORMAL",
    },
    "TRENDING_BEAR": {
        "strategy": "SHORT_RALLY",
        "bias": "BEARISH",
        "direction": "BEARISH",
        "risk_mode": "NORMAL",
    },
    "BULL_PULLBACK": {
        "strategy": "WAIT_FOR_LONG_RECLAIM",
        "bias": "BULLISH_PULLBACK",
        "direction": "BULLISH",
        "risk_mode": "REDUCED",
    },
    "BEAR_RALLY": {
        "strategy": "WAIT_FOR_SHORT_REJECTION",
        "bias": "BEARISH_RALLY",
        "direction": "BEARISH",
        "risk_mode": "REDUCED",
    },
    "RANGE_ACCUMULATION": {
        "strategy": "BUY_RANGE_LOW_OR_BREAKOUT",
        "bias": "ACCUMULATION",
        "direction": "BULLISH",
        "risk_mode": "REDUCED",
    },
    "RANGE_DISTRIBUTION": {
        "strategy": "SELL_RANGE_HIGH_OR_BREAKDOWN",
        "bias": "DISTRIBUTION",
        "direction": "BEARISH",
        "risk_mode": "REDUCED",
    },
    "RANGE_NEUTRAL": {
        "strategy": "WAIT_RANGE_EXTREMES",
        "bias": "NEUTRAL",
        "direction": "NEUTRAL",
        "risk_mode": "REDUCED",
    },
    "HIGH_VOLATILITY_BREAKOUT": {
        "strategy": "BUY_BREAKOUT_CONFIRMATION",
        "bias": "BULLISH_VOLATILE",
        "direction": "BULLISH",
        "risk_mode": "STRICT",
    },
    "HIGH_VOLATILITY_BREAKDOWN": {
        "strategy": "SHORT_BREAKDOWN_CONFIRMATION",
        "bias": "BEARISH_VOLATILE",
        "direction": "BEARISH",
        "risk_mode": "STRICT",
    },
    "LOW_VOLATILITY_COMPRESSION": {
        "strategy": "WAIT_EXPANSION",
        "bias": "NEUTRAL_COMPRESSION",
        "direction": "NEUTRAL",
        "risk_mode": "STRICT",
    },
    "LIQUIDITY_GRAB_BULLISH": {
        "strategy": "BUY_AFTER_SWEEP_RECLAIM",
        "bias": "BULLISH_REVERSAL",
        "direction": "BULLISH",
        "risk_mode": "STRICT",
    },
    "LIQUIDITY_GRAB_BEARISH": {
        "strategy": "SHORT_AFTER_SWEEP_REJECTION",
        "bias": "BEARISH_REVERSAL",
        "direction": "BEARISH",
        "risk_mode": "STRICT",
    },
    "MANIPULATION_PHASE": {
        "strategy": "WAIT",
        "bias": "DANGEROUS_NEUTRAL",
        "direction": "NEUTRAL",
        "risk_mode": "BLOCK",
    },
}


def detect_regime(features):
    return _detect_regime(
        features,
        trending_bull_momentum=62,
        trending_bear_momentum=38,
    )


def detect_regime_momentum_boundary_research(features):
    """Research-only detector aligned to the feature factory's 40-60 bounds."""
    return _detect_regime(
        features,
        trending_bull_momentum=60,
        trending_bear_momentum=40,
    )


def _detect_regime(
    features,
    *,
    trending_bull_momentum,
    trending_bear_momentum,
):
    trend = _score(features, "TrendScore")
    momentum = _score(features, "MomentumScore")
    volatility = _score(features, "VolatilityScore")
    liquidity = _score(features, "LiquidityScore")
    final_score = _score(features, "FinalScore")

    if liquidity >= 88 and volatility >= 82:
        if momentum >= 58 and trend >= 45:
            return _result(
                "LIQUIDITY_GRAB_BULLISH",
                84,
                "High liquidity and volatility with bullish reclaim pressure",
            )
        if momentum <= 42 and trend <= 55:
            return _result(
                "LIQUIDITY_GRAB_BEARISH",
                84,
                "High liquidity and volatility with bearish rejection pressure",
            )

        return _result(
            "MANIPULATION_PHASE",
            86,
            "Liquidity and volatility are both extreme without clean direction",
        )

    if volatility >= 82 and trend >= 64 and momentum >= 58:
        return _result(
            "HIGH_VOLATILITY_BREAKOUT",
            82,
            "High volatility expansion with bullish trend and momentum",
        )

    if volatility >= 82 and trend <= 36 and momentum <= 42:
        return _result(
            "HIGH_VOLATILITY_BREAKDOWN",
            82,
            "High volatility expansion with bearish trend and momentum",
        )

    if volatility <= 25 and 38 <= trend <= 62:
        return _result(
            "LOW_VOLATILITY_COMPRESSION",
            76,
            "Volatility compression inside a non-trending structure",
        )

    if trend >= 72 and momentum >= trending_bull_momentum:
        return _result(
            "TRENDING_BULL",
            _confidence(78, trend, momentum),
            "Trend and momentum are strongly bullish",
        )

    if trend <= 28 and momentum <= trending_bear_momentum:
        return _result(
            "TRENDING_BEAR",
            _confidence(78, 100 - trend, 100 - momentum),
            "Trend and momentum are strongly bearish",
        )

    if trend >= 60 and momentum < 52:
        return _result(
            "BULL_PULLBACK",
            _confidence(66, trend, 100 - momentum),
            "Bullish trend with lower-timeframe momentum pullback",
        )

    if trend <= 40 and momentum > 48:
        return _result(
            "BEAR_RALLY",
            _confidence(66, 100 - trend, momentum),
            "Bearish trend with counter-trend rally pressure",
        )

    if 40 <= trend <= 62 and momentum >= 52 and liquidity >= 55:
        return _result(
            "RANGE_ACCUMULATION",
            _confidence(62, momentum, liquidity),
            "Range structure with accumulation pressure",
        )

    if 38 <= trend <= 60 and momentum <= 48 and liquidity >= 55:
        return _result(
            "RANGE_DISTRIBUTION",
            _confidence(62, 100 - momentum, liquidity),
            "Range structure with distribution pressure",
        )

    if final_score >= 64:
        return _result(
            "RANGE_ACCUMULATION",
            _confidence(60, final_score, liquidity),
            "Positive composite score without clean trend confirmation",
        )

    if final_score <= 36:
        return _result(
            "RANGE_DISTRIBUTION",
            _confidence(60, 100 - final_score, liquidity),
            "Negative composite score without clean trend confirmation",
        )

    return _result(
        "RANGE_NEUTRAL",
        58,
        "Mixed feature state without directional regime confirmation",
    )


def regime_direction(regime):
    definition = REGIME_DEFINITIONS.get(str(regime or "").upper())
    if definition is None:
        return "UNKNOWN"
    return definition["direction"]


def _result(regime, confidence, reason):
    definition = REGIME_DEFINITIONS[regime]

    return {
        "regime": regime,
        "confidence": min(95, max(0, round(float(confidence), 2))),
        "strategy": definition["strategy"],
        "bias": definition["bias"],
        "direction": definition["direction"],
        "risk_mode": definition["risk_mode"],
        "reason": reason,
    }


def _confidence(base, primary, secondary):
    return base + max(0, primary - 50) * 0.18 + max(0, secondary - 50) * 0.12


def _score(features, name):
    value = getattr(features, name, None)

    if value is None:
        return 50.0

    return float(value)
