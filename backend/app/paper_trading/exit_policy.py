from app.trading.futures_cost_model import DEFAULT_FEE_BPS
from app.trading.futures_cost_model import trade_cost_profile


PAPER_STAGED_EXIT_POLICY = "PAPER_STAGED_EXIT_V1"
PAPER_EXIT_MONITOR_TIMEFRAME = "5m"
LEGACY_BTC_1H_STAGED_EXIT_POLICY = "BTC_1H_STAGED_V1"
STAGED_EXIT_POLICIES = frozenset(
    {PAPER_STAGED_EXIT_POLICY, LEGACY_BTC_1H_STAGED_EXIT_POLICY}
)
PAPER_ENTRY_TIMEFRAMES = frozenset({"1h", "2h", "4h", "1d"})
PAPER_STOP_LOSS_PERCENT = 0.75
PAPER_TARGET1_PERCENT = 1.5
PAPER_TARGET2_PERCENT = 2.3
PAPER_TARGET1_FRACTION = 0.5
PAPER_MAX_HOLD_HOURS = 48

# Backward-compatible names for callers and persisted BTC 1h trades created
# before the policy was expanded to the complete official paper-trading stack.
BTC_1H_STAGED_EXIT_POLICY = LEGACY_BTC_1H_STAGED_EXIT_POLICY
BTC_1H_STOP_LOSS_PERCENT = PAPER_STOP_LOSS_PERCENT
BTC_1H_TARGET1_PERCENT = PAPER_TARGET1_PERCENT
BTC_1H_TARGET2_PERCENT = PAPER_TARGET2_PERCENT
BTC_1H_TARGET1_FRACTION = PAPER_TARGET1_FRACTION
BTC_1H_MAX_HOLD_HOURS = PAPER_MAX_HOLD_HOURS


def paper_exit_policy_for(symbol, timeframe):
    if not str(symbol or "").strip():
        return None
    if str(timeframe or "").strip().lower() not in PAPER_ENTRY_TIMEFRAMES:
        return None

    return {
        "name": PAPER_STAGED_EXIT_POLICY,
        "stop_loss_percent": PAPER_STOP_LOSS_PERCENT,
        "target1_percent": PAPER_TARGET1_PERCENT,
        "target2_percent": PAPER_TARGET2_PERCENT,
        "target1_fraction": PAPER_TARGET1_FRACTION,
        "max_hold_hours": PAPER_MAX_HOLD_HOURS,
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
        "cost_model": "paper_staged_exit_v1",
        "fee_bps_per_side": float(fee_bps),
        "estimated_round_trip_fee_percent": round(float(fee_bps) * 2 / 100, 4),
    }


def approval_target_for_policy(exit_policy, target1, target2):
    if is_staged_exit_policy(exit_policy) and target2 is not None:
        return target2
    return target1


def is_staged_exit_policy(exit_policy):
    return str(exit_policy or "").strip().upper() in STAGED_EXIT_POLICIES


def _price_at_percent(entry, percent, precision):
    return round(entry * (1 + float(percent) / 100), int(precision))
