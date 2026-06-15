
def build_trade_plan(signal, current_price, atr=None):

    if signal == "WAIT":

        return {
            "entry": None,
            "stop_loss": None,
            "target1": None,
            "target2": None,
            "risk_reward": 0,
        }

    if atr is None:

        atr = current_price * 0.01

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
        "entry": round(entry, 2),
        "stop_loss": round(stop, 2),
        "target1": round(target1, 2),
        "target2": round(target2, 2),
        "atr":atr,
        "risk_reward": rr,
    }


def risk_level(confidence):

    if confidence >= 80:

        return "LOW"

    if confidence >= 60:

        return "MEDIUM"

    return "HIGH"