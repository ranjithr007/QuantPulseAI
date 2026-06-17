
def build_trade_plan(signal, current_price, atr=None):
    precision = price_precision(current_price)

    if atr is None:

        atr = current_price * 0.01

    if signal == "WAIT":

        return {
            "entry": None,
            "stop_loss": None,
            "target1": None,
            "target2": None,
            "atr": atr,
            "risk_reward": 0,
        }

    if signal == "LONG":

        entry = current_price

        stop = entry - atr

        target1 = entry + atr * 2

        target2 = entry + atr * 3

    else:

        entry = current_price

        stop = entry + atr

        target1 = entry - atr * 2

        target2 = entry - atr * 3

    risk = abs(entry - stop)

    reward = abs(target1 - entry)

    rr = round(reward / risk, 2)

    return {
        "entry": round(entry, precision),
        "stop_loss": round(stop, precision),
        "target1": round(target1, precision),
        "target2": round(target2, precision),
        "atr": round(atr, precision),
        "price_precision": precision,
        "risk_reward": rr,
    }


def risk_level(confidence):

    if confidence >= 80:

        return "LOW"

    if confidence >= 60:

        return "MEDIUM"

    return "HIGH"


def price_precision(price):
    if price < 1:
        return 6

    if price < 10:
        return 5

    if price < 100:
        return 4

    return 2
