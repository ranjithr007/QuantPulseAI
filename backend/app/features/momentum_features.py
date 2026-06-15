def calculate_momentum(candles):

    gains = 0
    losses = 0

    closes = [c.close_price for c in candles[-14:]]

    for i in range(1, len(closes)):

        diff = closes[i] - closes[i - 1]

        if diff > 0:
            gains += diff
        else:
            losses -= diff

    if losses == 0:
        rsi = 100
    else:
        rsi = 100 - (100 / (1 + (gains / losses)))

    if rsi > 60:
        return 80

    if rsi < 40:
        return 25

    return 50