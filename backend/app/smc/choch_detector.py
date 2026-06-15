
def detect_choch(candles):

    if len(candles) < 10:

        return False

    recent = candles[:5]

    old = candles[5:10]

    recent_high = max(x.high_price for x in recent)

    old_high = max(x.high_price for x in old)

    recent_low = min(x.low_price for x in recent)

    old_low = min(x.low_price for x in old)

    if recent_high > old_high and recent_low > old_low:

        return True

    if recent_high < old_high and recent_low < old_low:

        return True

    return False