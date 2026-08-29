from app.trading.futures_cost_model import DEFAULT_FEE_BPS
from app.trading.futures_cost_model import target_for_net_risk_reward
from app.trading.futures_cost_model import trade_cost_profile


PAPER_STAGED_EXIT_POLICY = "PAPER_STAGED_EXIT_V2"
PAPER_ADAPTIVE_EXIT_POLICY = "PAPER_ATR_STRUCTURE_V1"
PAPER_EXIT_MONITOR_TIMEFRAME = "5m"
LEGACY_PAPER_STAGED_EXIT_POLICY = "PAPER_STAGED_EXIT_V1"
LEGACY_BTC_1H_STAGED_EXIT_POLICY = "BTC_1H_STAGED_V1"
STAGED_EXIT_POLICIES = frozenset(
    {
        PAPER_STAGED_EXIT_POLICY,
        PAPER_ADAPTIVE_EXIT_POLICY,
        LEGACY_PAPER_STAGED_EXIT_POLICY,
        LEGACY_BTC_1H_STAGED_EXIT_POLICY,
    }
)
PAPER_ENTRY_TIMEFRAMES = frozenset({"1h", "2h", "4h", "1d"})
PAPER_STOP_LOSS_PERCENT = 0.75
PAPER_TARGET1_PERCENT = 1.5
PAPER_TARGET2_PERCENT = 2.3
PAPER_TARGET1_FRACTION = 0.75
PAPER_TARGET1_STOP_PROGRESS_FRACTION = 0.5
PAPER_TARGET2_TRAIL_TRIGGER_FRACTION = 0.75
PAPER_MAX_HOLD_HOURS = 48
PAPER_ADAPTIVE_MIN_ATR_MULTIPLE = 1.0
PAPER_ADAPTIVE_STRUCTURE_BUFFER_ATR = 0.25
PAPER_ADAPTIVE_MAX_ATR_MULTIPLE = 2.5
PAPER_ADAPTIVE_TARGET1_NET_RR = 1.5
PAPER_ADAPTIVE_TARGET2_NET_RR = 2.3

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
        "target1_stop_progress_fraction": PAPER_TARGET1_STOP_PROGRESS_FRACTION,
        "target2_trail_trigger_fraction": PAPER_TARGET2_TRAIL_TRIGGER_FRACTION,
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
    execution_profile=None,
    atr=None,
    structure_level=None,
    stop_loss_percent=None,
):
    policy = paper_exit_policy_for(symbol, timeframe)
    if policy is None:
        return None

    normalized_side = str(side or "").strip().upper()
    direction = 1 if normalized_side in {"BUY", "LONG"} else -1
    entry = float(entry)
    adaptive = str(execution_profile or "").upper() in {
        "TREND_PULLBACK",
        "RANGE_REVERSION",
        PAPER_ADAPTIVE_EXIT_POLICY,
    }
    if adaptive:
        stop_loss, adaptive_details = _adaptive_stop(
            normalized_side,
            entry,
            atr=atr,
            structure_level=structure_level,
            stop_loss_percent=stop_loss_percent,
            precision=price_precision,
        )
        target1 = _net_rr_target(
            normalized_side,
            entry,
            stop_loss,
            PAPER_ADAPTIVE_TARGET1_NET_RR,
            confidence,
            fee_bps,
            price_precision,
        )
        target2 = _net_rr_target(
            normalized_side,
            entry,
            stop_loss,
            PAPER_ADAPTIVE_TARGET2_NET_RR,
            confidence,
            fee_bps,
            price_precision,
        )
        policy = {
            **policy,
            "name": PAPER_ADAPTIVE_EXIT_POLICY,
            "stop_loss_percent": round(abs(entry - stop_loss) / entry * 100, 4),
            "target1_percent": round(abs(target1 - entry) / entry * 100, 4),
            "target2_percent": round(abs(target2 - entry) / entry * 100, 4),
            "execution_profile": str(execution_profile or "").upper(),
            **adaptive_details,
        }
    else:
        stop_loss = _price_at_percent(
            entry,
            -direction * (
                float(stop_loss_percent)
                if stop_loss_percent is not None
                else policy["stop_loss_percent"]
            ),
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
        "cost_model": (
            "paper_atr_structure_net_rr_v1"
            if adaptive
            else "paper_staged_exit_v1"
        ),
        "fee_bps_per_side": float(fee_bps),
        "estimated_round_trip_fee_percent": round(float(fee_bps) * 2 / 100, 4),
    }


def approval_target_for_policy(exit_policy, target1, target2):
    if is_staged_exit_policy(exit_policy) and target2 is not None:
        return target2
    return target1


def is_staged_exit_policy(exit_policy):
    return str(exit_policy or "").strip().upper() in STAGED_EXIT_POLICIES


def target1_protection_stop(side, entry, target1, price_precision=None):
    """Lock half of the entry-to-T1 move after the T1 partial exit."""
    price = float(entry) + (
        float(target1) - float(entry)
    ) * PAPER_TARGET1_STOP_PROGRESS_FRACTION
    if price_precision is None:
        return price
    return round(price, int(price_precision))


def target2_trail_trigger(target1, target2, price_precision=None):
    """Return the price 75% of the way from T1 to T2."""
    price = float(target1) + (
        float(target2) - float(target1)
    ) * PAPER_TARGET2_TRAIL_TRIGGER_FRACTION
    if price_precision is None:
        return price
    return round(price, int(price_precision))


def _price_at_percent(entry, percent, precision):
    return round(entry * (1 + float(percent) / 100), int(precision))


def _adaptive_stop(
    side,
    entry,
    *,
    atr,
    structure_level,
    stop_loss_percent,
    precision,
):
    atr_value = _positive_number(atr)
    if atr_value is None and stop_loss_percent is not None:
        atr_value = entry * float(stop_loss_percent) / 100
    if atr_value is None:
        raise ValueError("Fresh ATR is required for an adaptive paper exit")

    minimum_distance = atr_value * PAPER_ADAPTIVE_MIN_ATR_MULTIPLE
    maximum_distance = atr_value * PAPER_ADAPTIVE_MAX_ATR_MULTIPLE
    structure = _positive_number(structure_level)
    if side == "LONG":
        volatility_stop = entry - minimum_distance
        structure_stop = (
            structure - atr_value * PAPER_ADAPTIVE_STRUCTURE_BUFFER_ATR
            if structure is not None and structure < entry
            else volatility_stop
        )
        raw_stop = min(volatility_stop, structure_stop)
        raw_stop = max(raw_stop, entry - maximum_distance)
    else:
        volatility_stop = entry + minimum_distance
        structure_stop = (
            structure + atr_value * PAPER_ADAPTIVE_STRUCTURE_BUFFER_ATR
            if structure is not None and structure > entry
            else volatility_stop
        )
        raw_stop = max(volatility_stop, structure_stop)
        raw_stop = min(raw_stop, entry + maximum_distance)
    return round(raw_stop, int(precision)), {
        "atr": atr_value,
        "atr_stop_multiple": round(abs(entry - raw_stop) / atr_value, 4),
        "structure_level": structure,
        "stop_model": "MAX_1ATR_OR_STRUCTURE_PLUS_0_25ATR_CAPPED_2_5ATR",
    }


def _net_rr_target(side, entry, stop_loss, net_rr, confidence, fee_bps, precision):
    value = target_for_net_risk_reward(
        side,
        entry,
        stop_loss,
        net_rr,
        confidence=confidence,
        fee_bps=fee_bps,
    )
    # Round away from entry so rounding cannot reduce the requested net RR.
    scale = 10 ** int(precision)
    if side == "LONG":
        from math import ceil

        return ceil(value * scale) / scale
    from math import floor

    return floor(value * scale) / scale


def _positive_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None
