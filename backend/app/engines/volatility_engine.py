from app.engines.atr_engine import ATREngine


class VolatilityEngine:
    def analyze(self, candles):
        if not candles:
            return {
                "atr": 0,
                "atr_percent": 0,
                "volatility_state": "UNKNOWN",
                "volatility_score": 0,
            }

        latest_close = float(candles[-1].close_price)
        atr = ATREngine().calculate(candles)
        atr_percent = (atr / latest_close) * 100 if latest_close else 0

        if atr_percent >= 3:
            state = "HIGH"
            score = 80
        elif atr_percent >= 1:
            state = "NORMAL"
            score = 50
        else:
            state = "LOW"
            score = 25

        return {
            "atr": round(atr, 8),
            "atr_percent": round(atr_percent, 4),
            "volatility_state": state,
            "volatility_score": score,
        }
