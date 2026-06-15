
def detect_liquidity_sweep(candles):

    last = candles[0]

    highs = [c.high_price for c in candles[1:10]]

    lows = [c.low_price for c in candles[1:10]]

    if last.high_price > max(highs) and last.close_price < max(highs):

        return {"detected": True, "price": last.high_price}

    if last.low_price < min(lows) and last.close_price > min(lows):

        return {"detected": True, "price": last.low_price}

    return {"detected": False, "price": 0}