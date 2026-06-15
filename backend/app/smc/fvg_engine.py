class FVGEngine:

    def detect(self, candles):

        c1 = candles[-3]
        c3 = candles[-1]

        if c1.high_price < c3.low_price:

            return {"detected": 1, "type": "BULLISH", "high": c3.low_price, "low": c1.high_price}

        if c1.low_price > c3.high_price:

            return {"detected": 1, "type": "BEARISH", "high": c1.low_price, "low": c3.high_price}

        return {"detected": 0}