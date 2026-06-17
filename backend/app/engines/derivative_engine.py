class DerivativeEngine:
    def analyze(self, funding_rate=None, open_interest_delta=None, long_short_ratio=None):
        score = 0
        reasons = []

        if funding_rate is not None:
            if funding_rate > 0.03:
                score -= 25
                reasons.append("Funding elevated; long crowding risk")
            elif funding_rate < -0.03:
                score += 25
                reasons.append("Funding deeply negative; short squeeze risk")

        if open_interest_delta is not None:
            if open_interest_delta > 0:
                reasons.append("Open interest expanding")
            elif open_interest_delta < 0:
                reasons.append("Open interest contracting")

        if long_short_ratio is not None:
            if long_short_ratio > 1.5:
                score -= 15
                reasons.append("Long/short ratio crowded long")
            elif long_short_ratio < 0.67:
                score += 15
                reasons.append("Long/short ratio crowded short")

        if score >= 20:
            bias = "BULLISH_SQUEEZE_RISK"
        elif score <= -20:
            bias = "BEARISH_LONG_CROWDING"
        else:
            bias = "NEUTRAL"

        return {
            "bias": bias,
            "score": score,
            "reasons": reasons,
        }
