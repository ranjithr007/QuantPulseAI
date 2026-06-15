
def detect_absorption(delta, price_change):

    if price_change < 0 and delta > 0:

        return "SELLERS_ABSORBED"

    if price_change > 0 and delta < 0:

        return "BUYERS_ABSORBED"

    return "NONE"