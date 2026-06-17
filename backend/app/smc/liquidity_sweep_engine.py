from app.smc.liquidity_sweep_detector import detect_liquidity_sweep


class LiquiditySweepEngine:
    def analyze(self, candles):
        if len(candles) < 10:
            return {
                "detected": False,
                "direction": "NONE",
                "price": 0,
                "confidence": 0,
                "reason": "At least 10 candles are required",
            }

        result = detect_liquidity_sweep(candles)

        if not result["detected"]:
            return {
                "detected": False,
                "direction": "NONE",
                "price": 0,
                "confidence": 0,
                "reason": "No liquidity sweep detected",
            }

        latest = candles[0]
        direction = "BUY_SIDE_SWEEP" if result["price"] == latest.high_price else "SELL_SIDE_SWEEP"

        return {
            "detected": True,
            "direction": direction,
            "price": result["price"],
            "confidence": 70,
            "reason": "Price swept recent liquidity and closed back inside range",
        }
