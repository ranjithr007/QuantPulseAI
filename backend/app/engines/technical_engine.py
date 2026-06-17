class TechnicalEngine:
    def analyze(self, candles):
        closes = [float(c.close_price) for c in candles if c.close_price is not None]

        if len(closes) < 2:
            return {
                "trend": "UNKNOWN",
                "trend_score": 50,
                "momentum_score": 50,
                "reason": "Not enough candles",
            }

        latest = closes[-1]
        previous = closes[-2]
        sma_20 = _sma(closes, 20)
        sma_50 = _sma(closes, 50)

        trend_score = 50

        if sma_20 is not None and latest > sma_20:
            trend_score += 15
        elif sma_20 is not None:
            trend_score -= 15

        if sma_50 is not None and latest > sma_50:
            trend_score += 15
        elif sma_50 is not None:
            trend_score -= 15

        momentum = ((latest - previous) / previous) * 100 if previous else 0
        momentum_score = max(0, min(100, 50 + momentum * 10))

        if trend_score >= 65:
            trend = "BULLISH"
        elif trend_score <= 35:
            trend = "BEARISH"
        else:
            trend = "NEUTRAL"

        return {
            "trend": trend,
            "trend_score": round(trend_score, 2),
            "momentum_score": round(momentum_score, 2),
            "sma_20": sma_20,
            "sma_50": sma_50,
            "latest_close": latest,
        }


def _sma(values, period):
    if len(values) < period:
        return None

    return round(sum(values[-period:]) / period, 8)
