from app.regimes.rules import detect_regime


class RegimeEngine:
    def analyze(self, feature):
        if feature is None:
            return {
                "regime": "UNKNOWN",
                "confidence": 0,
                "strategy": "WAIT",
                "reason": "No feature input supplied",
            }

        return detect_regime(feature)
