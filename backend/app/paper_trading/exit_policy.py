from app.trading.futures_cost_model import DEFAULT_FEE_BPS
from app.trading.futures_cost_model import trade_cost_profile


BTC_1H_STAGED_EXIT_POLICY = "BTC_1H_STAGED_V1"
BTC_1H_STOP_LOSS_PERCENT = 0.75
BTC_1H_TARGET1_PERCENT = 1.5
BTC_1H_TARGET2_PERCENT = 2.3
BTC_1H_TARGET1_FRACTION = 0.5
BTC_1H_MAX_HOLD_HOURS = 48


def paper_exit_policy_for(symbol, timeframe):
    if str(symbol or "").strip().upper() != "BTCUSDT":
        return None
    if str(timeframe or "").strip().lower() != "1h":
        return None

    return {
        "name": BTC_1H_STAGED_EXIT_POLICY,
        "stop_loss_percent": BTC_1H_STOP_LOSS_PERCENT,
        "target1_percent": BTC_1H_TARGET1_PERCENT,
        "target2_percent": BTC_1H_TARGET2_PERCENT,
        "target1_fraction": BTC_1H_TARGET1_FRACTION,
        "max_hold_hours": BTC_1H_MAX_HOLD_HOURS,
    }


def build_policy_trade_levels(
    side,
    entry,
    *,
    symbol,
    timeframe,
    confidence,
    fee_bps=DEFAULT_FEE_BPS,
    price_precision=2,
):
    policy = paper_exit_policy_for(symbol, timeframe)
    if policy is None:
        return None

    normalized_side = str(side or "").strip().upper()
    direction = 1 if normalized_side in {"BUY", "LONG"} else -1
    entry = float(entry)
    stop_loss = _price_at_percent(
        entry,
        -direction * policy["stop_loss_percent"],
        price_precision,
    )
    target1 = _price_at_percent(
        entry,
        direction * policy["target1_percent"],
        price_precision,
    )
    target2 = _price_at_percent(
        entry,
        direction * policy["target2_percent"],
        price_precision,
    )
    target1_profile = trade_cost_profile(
        normalized_side,
        entry,
        stop_loss,
        target1,
        confidence=confidence,
        fee_bps=fee_bps,
    )
    target2_profile = trade_cost_profile(
        normalized_side,
        entry,
        stop_loss,
        target2,
        confidence=confidence,
        fee_bps=fee_bps,
    )
    return {
        **policy,
        "stop_loss": stop_loss,
        "target1": target1,
        "target2": target2,
        "target1_net_risk_reward": target1_profile["net_risk_reward"],
        "target2_net_risk_reward": target2_profile["net_risk_reward"],
        "target1_gross_risk_reward": target1_profile["gross_risk_reward"],
        "target2_gross_risk_reward": target2_profile["gross_risk_reward"],
        "cost_model": "paper_btc_1h_staged_v1",
        "fee_bps_per_side": float(fee_bps),
        "estimated_round_trip_fee_percent": round(float(fee_bps) * 2 / 100, 4),
    }


def approval_target_for_policy(exit_policy, target1, target2):
    if exit_policy == BTC_1H_STAGED_EXIT_POLICY and target2 is not None:
        return target2
    return target1


def _price_at_percent(entry, percent, precision):
    return round(entry * (1 + float(percent) / 100), int(precision))
