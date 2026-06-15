def calculate_volatility(candles):

    if len(candles) < 14:
        return 0, 0

    trs = []

    for i in range(1, len(candles)):

        high = candles[i].high_price
        low = candles[i].low_price
        prev_close = candles[i - 1].close_price

        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))

        trs.append(tr)

    atr = sum(trs[-14:]) / 14

    current_price = candles[-1].close_price     

    atr_percent = (atr / current_price) * 100

    if atr_percent > 3:
        score = 90

    elif atr_percent > 1:
        score = 60

    else:
        score = 30

    return score, atr