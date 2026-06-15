def calculate_trend(candles):

    closes = [c.close_price for c in candles]

    if len(closes) < 50:
        return 50, "UNKNOWN"

    ema20 = sum(closes[-20:]) / 20

    ema50 = sum(closes[-50:]) / 50

    if ema20 > ema50:

        return 80, "BULLISH"

    elif ema20 < ema50:

        return 30, "BEARISH"

    return 50, "SIDEWAYS"