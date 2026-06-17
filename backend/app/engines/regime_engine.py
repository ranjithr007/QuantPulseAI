from app.regimes.regime_engine import analyze_market


class RegimeEngine:
    def analyze(self, feature):
        if feature is None:
            return {
                "regime": "UNKNOWN",
                "confidence": 0,
                "strategy": "WAIT",
                "reason": "No feature input supplied",
            }

        return analyze_market(feature)
