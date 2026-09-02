from math import isfinite

from app.governance.evidence_policy import FULL_SIZE_ENTRY_CONFIDENCE
from app.paper_trading.evidence_scope import production_paper_trade_records


PAPER_CAPITAL_INR = 200_000.0
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
    stop_loss_percent=0.75,
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
    stop_loss_percent = _finite_number("stop_loss_percent", stop_loss_percent)

    if leverage < 1:
        raise ValueError("Paper leverage must be at least 1")
    if fee_bps < 0:
        raise ValueError("Paper fee basis points cannot be negative")
    if not 0 <= remaining_fraction <= 1:
        raise ValueError("Remaining position fraction must be between 0 and 1")
    if stop_loss_percent <= 0:
        raise ValueError("Stop-loss percentage must be greater than zero")

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
        "stop_loss_percent": round(stop_loss_percent, 4),
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


def fit_inr_paper_sizing_to_margin_capacity(sizing, margin_capacity_inr):
    """Reduce a new paper position to the account's remaining safe margin.

    The 75/85 percent confidence tiers describe the requested position size.
    They must not make an otherwise valid coin fail merely because earlier
    positions already use part of the account-wide 85 percent margin budget.
    This function preserves the requested tier for auditability while scaling
    every monetary risk field by the same factor.  A zero capacity is left for
    the executor to reject; this helper never expands a position.
    """

    result = dict(sizing or {})
    requested_margin = _finite_number(
        "paper sizing margin",
        result.get("margin_used_inr") or 0,
    )
    margin_capacity = max(
        0.0,
        _finite_number("remaining paper margin capacity", margin_capacity_inr),
    )
    if (
        requested_margin <= 0
        or margin_capacity <= 0
        or requested_margin <= margin_capacity
    ):
        result.setdefault("capacity_adjusted", False)
        return result

    scale = margin_capacity / requested_margin
    requested_tier = result.get("position_tier")
    requested_allocation = result.get("allocation_percent")
    requested_notional = result.get("position_notional_inr")
    requested_max_loss = result.get("estimated_max_loss_inr")
    for key in (
        "position_notional_inr",
        "margin_used_inr",
        "remaining_notional_inr",
        "remaining_margin_inr",
        "estimated_stop_loss_inr",
        "estimated_round_trip_cost_inr",
        "estimated_max_loss_inr",
    ):
        if result.get(key) is not None:
            result[key] = round(float(result[key]) * scale, 2)

    result.update(
        {
            "position_tier": "CAPACITY_ADJUSTED",
            "allocation_percent": round(
                float(result.get("position_notional_inr") or 0)
                / PAPER_CAPITAL_INR
                * 100,
                4,
            ),
            "estimated_max_loss_percent": round(
                float(result.get("estimated_max_loss_inr") or 0)
                / PAPER_CAPITAL_INR
                * 100,
                4,
            ),
            "capacity_adjusted": True,
            "capacity_scale": round(scale, 6),
            "requested_position_tier": requested_tier,
            "requested_allocation_percent": requested_allocation,
            "requested_position_notional_inr": requested_notional,
            "requested_margin_inr": round(requested_margin, 2),
            "requested_estimated_max_loss_inr": requested_max_loss,
            "margin_capacity_at_entry_inr": round(margin_capacity, 2),
        }
    )
    return result


def build_inr_paper_wallet(
    trades,
    *,
    ledger_entries=None,
    ledger_realized_pnl_inr=None,
    ledger_entry_count=None,
    trade_realized_pnl_inr=None,
    current_prices=None,
    require_open_prices=False,
    leverage=DEFAULT_PAPER_LEVERAGE,
):
    trades = production_paper_trade_records(trades)
    if ledger_entries is not None:
        ledger_entries = production_paper_trade_records(ledger_entries)
    positions = []
    missing_price_symbols = []
    current_prices = {
        str(symbol).upper(): _finite_or_none(price)
        for symbol, price in (current_prices or {}).items()
    }
    for trade in trades or []:
        if str(_value(trade, "status") or "").upper() != "OPEN":
            continue
        remaining_fraction = (
            1.0
            if _value(trade, "remaining_position_fraction") is None
            else float(_value(trade, "remaining_position_fraction"))
        )
        sizing = _persisted_or_legacy_sizing(
            trade,
            leverage=leverage,
            remaining_fraction=remaining_fraction,
        )
        symbol = str(_value(trade, "symbol") or "").upper()
        current_price = current_prices.get(symbol)
        unrealized_pnl = _open_unrealized_pnl_inr(
            trade,
            current_price,
            sizing["remaining_notional_inr"],
        )
        if unrealized_pnl is None and require_open_prices:
            missing_price_symbols.append(symbol)
        positions.append(
            {
                "trade_id": _value(trade, "id"),
                "symbol": symbol,
                "margin_inr": sizing["remaining_margin_inr"],
                "notional_inr": sizing["remaining_notional_inr"],
                "current_price": current_price,
                "unrealized_pnl_inr": unrealized_pnl,
            }
        )

    committed_margin = round(sum(item["margin_inr"] for item in positions), 2)
    committed_notional = round(sum(item["notional_inr"] for item in positions), 2)
    if ledger_entries is not None:
        realized_pnl = round(
            float(ledger_realized_pnl_inr)
            if ledger_realized_pnl_inr is not None
            else sum(float(_value(entry, "delta_inr") or 0) for entry in ledger_entries),
            2,
        )
        accounting_source = "PERSISTED_LEDGER"
        ledger_payload = [
            {
                "id": _value(entry, "id"),
                "event_key": _value(entry, "event_key"),
                "paper_trade_id": _value(entry, "paper_trade_id"),
                "symbol": _value(entry, "symbol"),
                "event_type": _value(entry, "event_type"),
                "delta_inr": float(_value(entry, "delta_inr") or 0),
                "position_fraction": _value(entry, "position_fraction"),
                "created_at": _value(entry, "created_at"),
            }
            for entry in list(ledger_entries)[-100:]
        ]
    elif trade_realized_pnl_inr is not None:
        realized_pnl = round(float(trade_realized_pnl_inr), 2)
        accounting_source = "PERSISTED_TRADE_AGGREGATE"
        ledger_payload = []
    else:
        realized_pnl = round(_realized_pnl_from_trades(trades), 2)
        accounting_source = "PERSISTED_TRADE_SNAPSHOTS"
        ledger_payload = []
    wallet_balance = round(PAPER_CAPITAL_INR + realized_pnl, 2)
    unrealized_pnl = round(
        sum(float(item["unrealized_pnl_inr"] or 0) for item in positions),
        2,
    )
    equity = round(wallet_balance + unrealized_pnl, 2)
    valuation_complete = not missing_price_symbols
    margin_capital = max(0.0, min(PAPER_CAPITAL_INR, equity))
    maximum_margin = margin_capital * MAX_ACCOUNT_MARGIN_UTILIZATION_PERCENT / 100
    return {
        "currency": "INR",
        "margin_type": "INR-M",
        "paper_capital_inr": PAPER_CAPITAL_INR,
        "initial_capital_inr": PAPER_CAPITAL_INR,
        "realized_pnl_inr": realized_pnl,
        "unrealized_pnl_inr": unrealized_pnl,
        "wallet_balance_inr": wallet_balance,
        "equity_inr": equity,
        "valuation_complete": valuation_complete,
        "missing_price_symbols": sorted(set(missing_price_symbols)),
        "accounting_source": accounting_source,
        "ledger_entry_count": (
            int(ledger_entry_count)
            if ledger_entry_count is not None
            else len(ledger_entries or [])
        ),
        "ledger": ledger_payload,
        "leverage": float(leverage),
        "minimum_position_allocation_percent": MINIMUM_TIER_ALLOCATION_PERCENT,
        "maximum_position_allocation_percent": MAXIMUM_TIER_ALLOCATION_PERCENT,
        "maximum_position_notional_inr": PAPER_MAX_POSITION_INR,
        "maximum_margin_utilization_percent": MAX_ACCOUNT_MARGIN_UTILIZATION_PERCENT,
        "maximum_committed_margin_inr": round(maximum_margin, 2),
        "committed_margin_inr": committed_margin,
        "available_margin_inr": round(max(0.0, equity - committed_margin), 2),
        "remaining_margin_capacity_inr": round(
            max(0.0, maximum_margin - committed_margin),
            2,
        ),
        "margin_utilization_percent": round(
            committed_margin / equity * 100 if equity > 0 else 0,
            2,
        ),
        "committed_notional_inr": committed_notional,
        "open_position_count": len(positions),
        "positions": positions,
    }


def _open_unrealized_pnl_inr(trade, current_price, remaining_notional_inr):
    entry_price = _finite_or_none(_value(trade, "entry_price"))
    current_price = _finite_or_none(current_price)
    if (
        entry_price is None
        or entry_price <= 0
        or current_price is None
        or current_price <= 0
    ):
        return None

    if str(_value(trade, "side") or "").upper() == "SHORT":
        gross_percent = (entry_price - current_price) / entry_price * 100
    else:
        gross_percent = (current_price - entry_price) / entry_price * 100
    fee_bps = max(0.0, _finite_or_none(_value(trade, "fee_bps")) or 0.0)
    net_percent = gross_percent - fee_bps * 2 / 100
    return round(float(remaining_notional_inr) * net_percent / 100, 2)


def _persisted_or_legacy_sizing(trade, *, leverage, remaining_fraction):
    notional = _value(trade, "position_notional_inr")
    margin = _value(trade, "margin_used_inr")
    persisted_leverage = _value(trade, "leverage")
    allocation = _value(trade, "allocation_percent")
    if notional is None or margin is None:
        return build_inr_paper_sizing(
            _value(trade, "confidence") or 0,
            leverage=leverage,
            fee_bps=_value(trade, "fee_bps") or 7.5,
            remaining_fraction=remaining_fraction,
        )

    return {
        "remaining_notional_inr": round(float(notional) * remaining_fraction, 2),
        "remaining_margin_inr": round(float(margin) * remaining_fraction, 2),
        "leverage": float(persisted_leverage or leverage),
        "allocation_percent": float(allocation or 0),
    }


def _realized_pnl_from_trades(trades):
    total = 0.0
    for trade in trades or []:
        status = str(_value(trade, "status") or "").upper()
        if status == "CLOSED":
            total += float(_value(trade, "realized_pnl_inr") or 0)
        elif status == "OPEN":
            total += float(_value(trade, "partial_realized_pnl_inr") or 0)
    return total


def _finite_number(name, value):
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not isfinite(number):
        raise ValueError(f"{name} must be a finite number")
    return number


def _finite_or_none(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _value(record, name):
    if isinstance(record, dict):
        return record.get(name)
    return getattr(record, name, None)
