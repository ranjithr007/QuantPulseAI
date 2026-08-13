
from app.trading.futures_cost_model import build_cost_adjusted_targets
from app.trading.futures_cost_model import DEFAULT_FEE_BPS
from app.trading.futures_cost_model import DEFAULT_STOP_LOSS_PERCENT


def build_trade_plan(
    signal,
    current_price,
    atr=None,
    confidence=50,
    fee_bps=DEFAULT_FEE_BPS,
):
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

    entry = current_price
    stop_distance = entry * (DEFAULT_STOP_LOSS_PERCENT / 100)

    if signal == "LONG":

        stop = entry - stop_distance

    else:

        stop = entry + stop_distance

    cost_adjustment = build_cost_adjusted_targets(
        signal,
        entry,
        stop,
        confidence=confidence,
        fee_bps=fee_bps,
        price_precision=precision,
    )
    target1 = cost_adjustment["target1"]
    target2 = cost_adjustment["target2"]

    return {
        "entry": round(entry, precision),
        "stop_loss": round(stop, precision),
        "target1": target1,
        "target2": target2,
        "target3": cost_adjustment["target3"],
        "atr": round(atr, precision),
        "stop_loss_percent": DEFAULT_STOP_LOSS_PERCENT,
        "price_precision": precision,
        "risk_reward": cost_adjustment["target1_net_risk_reward"],
        "gross_risk_reward": cost_adjustment["target1_gross_risk_reward"],
        "target2_net_risk_reward": cost_adjustment["target2_net_risk_reward"],
        "target3_net_risk_reward": cost_adjustment["target3_net_risk_reward"],
        "cost_model": cost_adjustment["cost_model"],
        "estimated_costs": cost_adjustment,
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
