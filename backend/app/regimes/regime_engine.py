from app.regimes.rules import detect_regime


def analyze_market(feature):

    result = detect_regime(feature)

    return {
        "symbol": feature.Symbol,
        "timeframe": feature.Timeframe,
        "regime": result["regime"],
        "confidence": result["confidence"],
        "strategy": result["strategy"],
    }