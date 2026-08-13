from math import ceil
from math import floor


DEFAULT_FEE_BPS = 7.5
DEFAULT_CONFIDENCE = 50.0
DEFAULT_STOP_LOSS_PERCENT = 5.0
TARGET1_NET_RISK_REWARD = 2.0
TARGET2_NET_RISK_REWARD = 3.0
TARGET3_NET_RISK_REWARD = 4.0


def build_cost_adjusted_targets(
    side,
    entry,
    stop_loss,
    *,
    confidence=DEFAULT_CONFIDENCE,
    fee_bps=DEFAULT_FEE_BPS,
    price_precision=2,
):
    side = _canonical_side(side)
    entry = float(entry)
    stop_loss = float(stop_loss)
    confidence = _clamp(float(confidence), 0, 100)
    fee_bps = max(0.0, float(fee_bps))
    slippage = estimate_slippage_rates(
        entry,
        stop_loss,
        confidence=confidence,
        risk_reward=TARGET1_NET_RISK_REWARD,
    )
    target1 = target_for_net_risk_reward(
        side,
        entry,
        stop_loss,
        TARGET1_NET_RISK_REWARD,
        fee_bps=fee_bps,
        slippage=slippage,
    )
    target2 = target_for_net_risk_reward(
        side,
        entry,
        stop_loss,
        TARGET2_NET_RISK_REWARD,
        fee_bps=fee_bps,
        slippage=slippage,
    )
    target3 = target_for_net_risk_reward(
        side,
        entry,
        stop_loss,
        TARGET3_NET_RISK_REWARD,
        fee_bps=fee_bps,
        slippage=slippage,
    )
    target1 = _round_outward(target1, price_precision, side)
    target2 = _round_outward(target2, price_precision, side)
    target3 = _round_outward(target3, price_precision, side)
    target1_profile = trade_cost_profile(
        side,
        entry,
        stop_loss,
        target1,
        confidence=confidence,
        fee_bps=fee_bps,
        slippage=slippage,
    )
    target2_profile = trade_cost_profile(
        side,
        entry,
        stop_loss,
        target2,
        confidence=confidence,
        fee_bps=fee_bps,
        slippage=slippage,
    )
    target3_profile = trade_cost_profile(
        side,
        entry,
        stop_loss,
        target3,
        confidence=confidence,
        fee_bps=fee_bps,
        slippage=slippage,
    )
    return {
        "target1": target1,
        "target2": target2,
        "target3": target3,
        "target1_net_risk_reward": target1_profile["net_risk_reward"],
        "target2_net_risk_reward": target2_profile["net_risk_reward"],
        "target3_net_risk_reward": target3_profile["net_risk_reward"],
        "target1_gross_risk_reward": target1_profile["gross_risk_reward"],
        "target2_gross_risk_reward": target2_profile["gross_risk_reward"],
        "target3_gross_risk_reward": target3_profile["gross_risk_reward"],
        "estimated_entry_fill": target1_profile["entry_fill"],
        "estimated_stop_fill": target1_profile["stop_fill"],
        "estimated_target1_fill": target1_profile["target_fill"],
        "estimated_target2_fill": target2_profile["target_fill"],
        "estimated_target3_fill": target3_profile["target_fill"],
        "fee_bps_per_side": fee_bps,
        "estimated_round_trip_fee_percent": round(fee_bps * 2 / 100, 4),
        "entry_slippage_percent": round(slippage["entry"] * 100, 4),
        "target_slippage_percent": round(slippage["target"] * 100, 4),
        "stop_slippage_percent": round(slippage["stop"] * 100, 4),
        "cost_model": "paper_futures_net_rr_v1",
    }


def target_for_net_risk_reward(
    side,
    entry,
    stop_loss,
    net_risk_reward,
    *,
    fee_bps=DEFAULT_FEE_BPS,
    slippage=None,
    confidence=DEFAULT_CONFIDENCE,
):
    side = _canonical_side(side)
    entry = float(entry)
    stop_loss = float(stop_loss)
    required_rr = float(net_risk_reward)
    if required_rr <= 0:
        raise ValueError("net_risk_reward must be greater than zero")
    slippage = slippage or estimate_slippage_rates(
        entry,
        stop_loss,
        confidence=confidence,
        risk_reward=required_rr,
    )
    fee_rate = max(0.0, float(fee_bps)) / 10_000
    entry_fill, stop_fill = _entry_and_stop_fills(side, entry, stop_loss, slippage)
    net_loss = _net_loss(side, entry_fill, stop_fill, fee_rate)

    if side == "LONG":
        denominator = (1 - slippage["target"]) * (1 - fee_rate)
        return (required_rr * net_loss + entry_fill * (1 + fee_rate)) / denominator

    denominator = (1 + slippage["target"]) * (1 + fee_rate)
    return (entry_fill * (1 - fee_rate) - required_rr * net_loss) / denominator


def trade_cost_profile(
    side,
    entry,
    stop_loss,
    target,
    *,
    confidence=DEFAULT_CONFIDENCE,
    fee_bps=DEFAULT_FEE_BPS,
    slippage=None,
):
    side = _canonical_side(side)
    entry = float(entry)
    stop_loss = float(stop_loss)
    target = float(target)
    slippage = slippage or estimate_slippage_rates(
        entry,
        stop_loss,
        confidence=confidence,
        risk_reward=TARGET1_NET_RISK_REWARD,
    )
    fee_rate = max(0.0, float(fee_bps)) / 10_000
    entry_fill, stop_fill = _entry_and_stop_fills(side, entry, stop_loss, slippage)
    target_fill = (
        target * (1 - slippage["target"])
        if side == "LONG"
        else target * (1 + slippage["target"])
    )
    net_loss = _net_loss(side, entry_fill, stop_fill, fee_rate)
    if side == "LONG":
        gross_reward = target_fill - entry_fill
    else:
        gross_reward = entry_fill - target_fill
    target_fees = fee_rate * (entry_fill + target_fill)
    net_reward = gross_reward - target_fees
    gross_risk = abs(entry - stop_loss)
    gross_target = abs(target - entry)
    return {
        "entry_fill": entry_fill,
        "stop_fill": stop_fill,
        "target_fill": target_fill,
        "net_loss": net_loss,
        "net_reward": net_reward,
        "net_risk_reward": round(net_reward / net_loss, 4) if net_loss > 0 else None,
        "gross_risk_reward": round(gross_target / gross_risk, 4) if gross_risk > 0 else None,
        "fee_bps_per_side": float(fee_bps),
        "slippage": dict(slippage),
    }


def estimate_slippage_rates(
    entry,
    stop_loss,
    *,
    confidence=DEFAULT_CONFIDENCE,
    risk_reward=TARGET1_NET_RISK_REWARD,
):
    entry_slippage = estimate_entry_slippage_rate(
        entry,
        stop_loss,
        confidence=confidence,
        risk_reward=risk_reward,
    )
    return {
        "entry": entry_slippage,
        "target": round(max(0.00005, entry_slippage * 0.5), 6),
        "stop": round(max(0.00005, entry_slippage * 1.25), 6),
    }


def estimate_entry_slippage_rate(
    entry,
    stop_loss,
    *,
    confidence=DEFAULT_CONFIDENCE,
    risk_reward=TARGET1_NET_RISK_REWARD,
):
    entry = float(entry)
    stop_distance_pct = (
        0.0
        if stop_loss is None or entry == 0
        else abs(entry - float(stop_loss)) / abs(entry)
    )
    confidence_penalty = max(0.0, 75 - float(confidence)) * 0.00001
    volatility_penalty = min(0.001, stop_distance_pct * 0.02)
    rr_penalty = max(0.0, 2.0 - float(risk_reward or 0)) * 0.0001
    return round(
        _clamp(
            0.00015 + confidence_penalty + volatility_penalty + rr_penalty,
            0.00005,
            0.003,
        ),
        6,
    )


def _entry_and_stop_fills(side, entry, stop_loss, slippage):
    if side == "LONG":
        return (
            entry * (1 + slippage["entry"]),
            stop_loss * (1 - slippage["stop"]),
        )
    return (
        entry * (1 - slippage["entry"]),
        stop_loss * (1 + slippage["stop"]),
    )


def _net_loss(side, entry_fill, stop_fill, fee_rate):
    gross_loss = (
        entry_fill - stop_fill
        if side == "LONG"
        else stop_fill - entry_fill
    )
    return gross_loss + fee_rate * (entry_fill + stop_fill)


def _round_outward(value, precision, side):
    factor = 10 ** int(precision)
    if side == "LONG":
        return ceil(float(value) * factor) / factor
    return floor(float(value) * factor) / factor


def _canonical_side(side):
    normalized = str(side or "").strip().upper()
    if normalized in {"BUY", "LONG"}:
        return "LONG"
    if normalized in {"SELL", "SHORT"}:
        return "SHORT"
    raise ValueError(f"Unsupported futures side: {side}")


def _clamp(value, minimum, maximum):
    return max(minimum, min(maximum, float(value)))
