
def detect_liquidity_sweep(candles):

    if len(candles) < 10:
        return {"detected": False, "price": 0}

    last = candles[-1]

    highs = [c.high_price for c in candles[-10:-1]]

    lows = [c.low_price for c in candles[-10:-1]]

    if last.high_price > max(highs) and last.close_price < max(highs):

        return {"detected": True, "price": last.high_price}

    if last.low_price < min(lows) and last.close_price > min(lows):

        return {"detected": True, "price": last.low_price}

    return {"detected": False, "price": 0}
