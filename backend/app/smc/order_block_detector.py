
def detect_order_block(candles):

    for c in candles[:20]:

        body = abs(c.close_price - c.open_price)

        candle_range = c.high_price - c.low_price

        if candle_range == 0:
            continue

        strength = body / candle_range

        if strength > 0.7:

            if c.close_price > c.open_price:

                return {"type": "BULLISH", "price": c.low_price}

            else:

                return {"type": "BEARISH", "price": c.high_price}

    return {"type": "NONE", "price": 0}