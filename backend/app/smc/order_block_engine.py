from app.smc.order_block_detector import detect_order_block


class OrderBlockEngine:
    def analyze(self, candles):
        if not candles:
            return {
                "type": "NONE",
                "price": 0,
                "confidence": 0,
                "reason": "No candles supplied",
            }

        result = detect_order_block(candles)

        if result["type"] == "NONE":
            return {
                "type": "NONE",
                "price": 0,
                "confidence": 0,
                "reason": "No strong impulse candle found",
            }

        return {
            "type": result["type"],
            "price": result["price"],
            "confidence": 65,
            "reason": f"{result['type']} order block detected from impulse candle",
        }
