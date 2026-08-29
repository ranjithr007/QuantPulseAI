
from app.trading.futures_cost_model import build_cost_adjusted_targets
from app.trading.futures_cost_model import DEFAULT_FEE_BPS
from app.trading.futures_cost_model import DEFAULT_STOP_LOSS_PERCENT
from app.paper_trading.exit_policy import build_policy_trade_levels


def build_trade_plan(
    signal,
    current_price,
    atr=None,
    confidence=50,
    fee_bps=DEFAULT_FEE_BPS,
    *,
    symbol=None,
    timeframe=None,
    execution_profile=None,
    structure_level=None,
    stop_loss_percent=None,
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
    policy_levels = build_policy_trade_levels(
        signal,
        entry,
        symbol=symbol,
        timeframe=timeframe,
        confidence=confidence,
        fee_bps=fee_bps,
        price_precision=precision,
        execution_profile=execution_profile,
        atr=atr,
        structure_level=structure_level,
        stop_loss_percent=stop_loss_percent,
    )
    if policy_levels is not None:
        return {
            "entry": round(entry, precision),
            "stop_loss": policy_levels["stop_loss"],
            "target1": policy_levels["target1"],
            "target2": policy_levels["target2"],
            "target3": None,
            "atr": round(atr, precision),
            "stop_loss_percent": policy_levels["stop_loss_percent"],
            "price_precision": precision,
            # Target 2 is the final reward target used by the 2R approval guard.
            "risk_reward": policy_levels["target2_net_risk_reward"],
            "gross_risk_reward": policy_levels["target2_gross_risk_reward"],
            "target1_net_risk_reward": policy_levels["target1_net_risk_reward"],
            "target2_net_risk_reward": policy_levels["target2_net_risk_reward"],
            "target3_net_risk_reward": None,
            "cost_model": policy_levels["cost_model"],
            "estimated_costs": policy_levels,
            "exit_policy": policy_levels["name"],
            "target1_fraction": policy_levels["target1_fraction"],
            "max_hold_hours": policy_levels["max_hold_hours"],
            "execution_profile": policy_levels.get("execution_profile"),
            "stop_model": policy_levels.get("stop_model"),
            "atr_stop_multiple": policy_levels.get("atr_stop_multiple"),
            "structure_level": policy_levels.get("structure_level"),
        }

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
