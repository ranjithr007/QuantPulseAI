
def detect_fvg(candles):

    if len(candles) < 3:

        return {"detected": False, "price": 0}

    c1 = candles[-3]
    c3 = candles[-1]

    if c1.high_price < c3.low_price:

        return {"detected": True, "price": c3.low_price}

    if c1.low_price > c3.high_price:

        return {"detected": True, "price": c3.high_price}

    return {"detected": False, "price": 0}
