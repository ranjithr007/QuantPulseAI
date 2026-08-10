def detect_bos(candles):

    if len(candles) < 5:

        return {"detected": False, "direction": "NONE"}

    last = candles[-1]

    previous_high = max(c.high_price for c in candles[-5:-1])

    previous_low = min(c.low_price for c in candles[-5:-1])

    if last.close_price > previous_high:

        return {"detected": True, "direction": "BULLISH"}

    if last.close_price < previous_low:

        return {"detected": True, "direction": "BEARISH"}

    return {"detected": False, "direction": "NONE"}
