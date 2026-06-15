def calculate_liquidity(candles):

    if len(candles) < 20:
        return 0

    latest_volume = candles[-1].volume

    avg_volume = sum(c.volume for c in candles[-20:]) / 20

    ratio = latest_volume / avg_volume if avg_volume > 0 else 0

    if ratio >= 2:

        score = 90

    elif ratio >= 1:

        score = 60

    else:

        score = 30

    return score