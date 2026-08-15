from math import isfinite

from app.governance.evidence_policy import FULL_SIZE_ENTRY_CONFIDENCE


PAPER_CAPITAL_INR = 100_000.0
MINIMUM_TIER_ALLOCATION_PERCENT = 75.0
MAXIMUM_TIER_ALLOCATION_PERCENT = 85.0
PAPER_MAX_POSITION_INR = PAPER_CAPITAL_INR * (
    MAXIMUM_TIER_ALLOCATION_PERCENT / 100
)
DEFAULT_PAPER_LEVERAGE = 5.0
MAX_ACCOUNT_MARGIN_UTILIZATION_PERCENT = 85.0


def build_inr_paper_sizing(
    confidence,
    *,
    leverage=DEFAULT_PAPER_LEVERAGE,
    fee_bps=7.5,
    remaining_fraction=1.0,
):
    """Return governed INR-M paper sizing without mixing INR with USDT prices.

    Contract prices can remain USDT-quoted, as on CoinDCX INR-M. Monetary
    exposure and margin are tracked independently in INR so no INR amount is
    divided by a USDT price without an exchange conversion rate.
    """

    confidence = _finite_number("confidence", confidence)
    leverage = _finite_number("leverage", leverage)
    fee_bps = _finite_number("fee_bps", fee_bps)
    remaining_fraction = _finite_number("remaining_fraction", remaining_fraction)

    if leverage < 1:
        raise ValueError("Paper leverage must be at least 1")
    if fee_bps < 0:
        raise ValueError("Paper fee basis points cannot be negative")
    if not 0 <= remaining_fraction <= 1:
        raise ValueError("Remaining position fraction must be between 0 and 1")

    allocation_percent = (
        MINIMUM_TIER_ALLOCATION_PERCENT
        if confidence < FULL_SIZE_ENTRY_CONFIDENCE
        else MAXIMUM_TIER_ALLOCATION_PERCENT
    )
    position_tier = (
        "MINIMUM"
        if confidence < FULL_SIZE_ENTRY_CONFIDENCE
        else "MAXIMUM"
    )
    position_notional_inr = PAPER_CAPITAL_INR * allocation_percent / 100
    margin_used_inr = position_notional_inr / leverage
    remaining_notional_inr = position_notional_inr * remaining_fraction
    remaining_margin_inr = margin_used_inr * remaining_fraction
    stop_loss_percent = 0.75
    estimated_round_trip_cost_percent = fee_bps * 2 / 100
    estimated_stop_loss_inr = position_notional_inr * stop_loss_percent / 100
    estimated_round_trip_cost_inr = (
        position_notional_inr * estimated_round_trip_cost_percent / 100
    )

    return {
        "currency": "INR",
        "margin_type": "INR-M",
        "paper_capital_inr": PAPER_CAPITAL_INR,
        "position_tier": position_tier,
        "allocation_percent": allocation_percent,
        "position_notional_inr": round(position_notional_inr, 2),
        "leverage": leverage,
        "margin_used_inr": round(margin_used_inr, 2),
        "remaining_fraction": remaining_fraction,
        "remaining_notional_inr": round(remaining_notional_inr, 2),
        "remaining_margin_inr": round(remaining_margin_inr, 2),
        "estimated_stop_loss_inr": round(estimated_stop_loss_inr, 2),
        "estimated_round_trip_cost_inr": round(
            estimated_round_trip_cost_inr,
            2,
        ),
        "estimated_max_loss_inr": round(
            estimated_stop_loss_inr + estimated_round_trip_cost_inr,
            2,
        ),
        "estimated_max_loss_percent": round(
            (estimated_stop_loss_inr + estimated_round_trip_cost_inr)
            / PAPER_CAPITAL_INR
            * 100,
            4,
        ),
    }


def build_inr_paper_wallet(trades, *, leverage=DEFAULT_PAPER_LEVERAGE):
    positions = []
    for trade in trades or []:
        if str(_value(trade, "status") or "").upper() != "OPEN":
            continue
        sizing = build_inr_paper_sizing(
            _value(trade, "confidence") or 0,
            leverage=leverage,
            fee_bps=_value(trade, "fee_bps") or 7.5,
            remaining_fraction=(
                1.0
                if _value(trade, "remaining_position_fraction") is None
                else _value(trade, "remaining_position_fraction")
            ),
        )
        positions.append(
            {
                "trade_id": _value(trade, "id"),
                "symbol": _value(trade, "symbol"),
                "margin_inr": sizing["remaining_margin_inr"],
                "notional_inr": sizing["remaining_notional_inr"],
            }
        )

    committed_margin = round(sum(item["margin_inr"] for item in positions), 2)
    committed_notional = round(sum(item["notional_inr"] for item in positions), 2)
    maximum_margin = PAPER_CAPITAL_INR * MAX_ACCOUNT_MARGIN_UTILIZATION_PERCENT / 100
    return {
        "currency": "INR",
        "margin_type": "INR-M",
        "paper_capital_inr": PAPER_CAPITAL_INR,
        "leverage": float(leverage),
        "minimum_position_allocation_percent": MINIMUM_TIER_ALLOCATION_PERCENT,
        "maximum_position_allocation_percent": MAXIMUM_TIER_ALLOCATION_PERCENT,
        "maximum_position_notional_inr": PAPER_MAX_POSITION_INR,
        "maximum_margin_utilization_percent": MAX_ACCOUNT_MARGIN_UTILIZATION_PERCENT,
        "maximum_committed_margin_inr": round(maximum_margin, 2),
        "committed_margin_inr": committed_margin,
        "available_margin_inr": round(max(0.0, PAPER_CAPITAL_INR - committed_margin), 2),
        "remaining_margin_capacity_inr": round(
            max(0.0, maximum_margin - committed_margin),
            2,
        ),
        "margin_utilization_percent": round(
            committed_margin / PAPER_CAPITAL_INR * 100,
            2,
        ),
        "committed_notional_inr": committed_notional,
        "open_position_count": len(positions),
        "positions": positions,
    }


def _finite_number(name, value):
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not isfinite(number):
        raise ValueError(f"{name} must be a finite number")
    return number


def _value(record, name):
    if isinstance(record, dict):
        return record.get(name)
    return getattr(record, name, None)
