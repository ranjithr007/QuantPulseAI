class ScoringEngine:

    def calculate(self, liquidity):

        score = 0

        if liquidity["long_squeeze_probability"] > 70:

            score -= 50

        if liquidity["short_squeeze_probability"] > 70:

            score += 50

        confidence = liquidity["confidence"]

        bias = "NEUTRAL"

        if score > 30:

            bias = "BULLISH"

        if score < -30:

            bias = "BEARISH"

        return {"score": score, "bias": bias, "confidence": confidence}