from datetime import datetime
from datetime import timedelta
from datetime import timezone

from app.paper_trading.inr_sizing import build_inr_paper_sizing
from app.paper_trading.inr_sizing import PAPER_CAPITAL_INR


DEFAULT_DAILY_LOSS_LIMIT_PERCENT = 4.0
DEFAULT_DAILY_WINDOW_HOURS = 24


def build_account_daily_pnl_snapshot(
    trades,
    current_prices=None,
    *,
    daily_loss_limit=DEFAULT_DAILY_LOSS_LIMIT_PERCENT,
    as_of=None,
    window_hours=DEFAULT_DAILY_WINDOW_HOURS,
    require_open_prices=False,
):
    """Build one account-level daily P&L guard from symbol-specific prices.

    Trade ``pnl_percent`` values describe the underlying price return. They are
    converted to account return using the governed risk percentage and stop
    distance, so a 4% move in one small position is not mistaken for a 4%
    account loss.
    """

    as_of = _naive_utc(as_of) or datetime.utcnow()
    cutoff = as_of - timedelta(hours=max(1, int(window_hours)))
    prices = {
        str(symbol).upper(): _safe_number(price)
        for symbol, price in (current_prices or {}).items()
        if _safe_number(price) is not None
    }
    contributions = []
    skipped = []
    open_trade_count = 0
    closed_window_trade_count = 0

    for trade in trades or []:
        status = str(_value(trade, "status") or "").upper()
        persisted_account_pnl_percent = None
        if status == "CLOSED":
            closed_at = _timestamp(_value(trade, "closed_at"))
            if closed_at is None or closed_at < cutoff or closed_at > as_of:
                continue
            closed_window_trade_count += 1
            market_pnl_percent = _safe_number(_value(trade, "pnl_percent"))
            realized_pnl_inr = _safe_number(_value(trade, "realized_pnl_inr"))
            if realized_pnl_inr is not None:
                persisted_account_pnl_percent = (
                    realized_pnl_inr / PAPER_CAPITAL_INR * 100
                )
            source = "REALIZED"
            valuation_price = _safe_number(_value(trade, "exit_price"))
        elif status == "OPEN":
            open_trade_count += 1
            symbol = str(_value(trade, "symbol") or "").upper()
            entry = _safe_number(_value(trade, "entry_price"))
            valuation_price = prices.get(symbol)
            if valuation_price is None and require_open_prices:
                skipped.append(
                    {
                        "trade_id": _value(trade, "id"),
                        "symbol": symbol,
                        "reason": "Fresh mark price is required for open-position valuation",
                    }
                )
                continue
            valuation_price = valuation_price if valuation_price is not None else entry
            market_pnl_percent = _open_net_pnl_percent(
                trade,
                entry,
                valuation_price,
            )
            source = "UNREALIZED"
        else:
            continue

        exposure_factor = _account_exposure_factor(trade)
        symbol = str(_value(trade, "symbol") or "").upper()
        if (
            persisted_account_pnl_percent is None
            and (market_pnl_percent is None or exposure_factor is None)
        ):
            skipped.append(
                {
                    "trade_id": _value(trade, "id"),
                    "symbol": symbol,
                    "reason": "Insufficient position-risk data for account weighting",
                }
            )
            continue

        account_pnl_percent = (
            persisted_account_pnl_percent
            if persisted_account_pnl_percent is not None
            else market_pnl_percent * exposure_factor
        )
        if status == "OPEN":
            target1_hit_at = _timestamp(_value(trade, "target1_hit_at"))
            if target1_hit_at is not None and cutoff <= target1_hit_at <= as_of:
                account_pnl_percent += (
                    (_safe_number(_value(trade, "partial_realized_pnl_inr")) or 0)
                    / PAPER_CAPITAL_INR
                    * 100
                )
        contributions.append(
            {
                "trade_id": _value(trade, "id"),
                "symbol": symbol,
                "status": status,
                "source": source,
                "market_pnl_percent": (
                    round(market_pnl_percent, 4)
                    if market_pnl_percent is not None
                    else None
                ),
                "account_exposure_factor": (
                    round(exposure_factor, 6)
                    if exposure_factor is not None
                    else None
                ),
                "account_pnl_percent": round(account_pnl_percent, 4),
                "account_pnl_source": (
                    "PERSISTED_REALIZED_INR"
                    if persisted_account_pnl_percent is not None
                    else "WEIGHTED_MARKET_RETURN"
                ),
                "valuation_price": valuation_price,
            }
        )

    combined = round(
        sum(item["account_pnl_percent"] for item in contributions),
        4,
    )
    valued_open_trade_count = sum(
        1 for item in contributions if item["source"] == "UNREALIZED"
    )
    limit = abs(float(daily_loss_limit))
    return {
        "scope": "ACCOUNT",
        "window_hours": int(window_hours),
        "as_of": as_of,
        "daily_pnl_percent": combined,
        "daily_loss_limit_percent": limit,
        "limit_reached": combined <= -limit,
        "risk_available": (
            not require_open_prices
            or valued_open_trade_count == open_trade_count
        ),
        "open_trade_count": open_trade_count,
        "valued_open_trade_count": valued_open_trade_count,
        "closed_window_trade_count": closed_window_trade_count,
        "open_contribution_percent": round(
            sum(
                item["account_pnl_percent"]
                for item in contributions
                if item["source"] == "UNREALIZED"
            ),
            4,
        ),
        "closed_contribution_percent": round(
            sum(
                item["account_pnl_percent"]
                for item in contributions
                if item["source"] == "REALIZED"
            ),
            4,
        ),
        "contributions": contributions,
        "skipped": skipped,
        "calculation": "position_size_weighted_account_return_v1",
    }


def _open_net_pnl_percent(trade, entry, current):
    if entry is None or current is None or entry <= 0:
        return None
    if str(_value(trade, "side") or "").upper() == "SHORT":
        gross = ((entry - current) / entry) * 100
    else:
        gross = ((current - entry) / entry) * 100
    fee_bps = max(0.0, _safe_number(_value(trade, "fee_bps")) or 0.0)
    estimated_round_trip_fees = fee_bps * 2 / 100
    return gross - estimated_round_trip_fees


def _account_exposure_factor(trade):
    persisted_notional = _safe_number(_value(trade, "position_notional_inr"))
    if persisted_notional is not None and persisted_notional >= 0:
        remaining_fraction = _safe_number(
            _value(trade, "remaining_position_fraction")
        )
        if remaining_fraction is None:
            remaining_fraction = 1.0
        return persisted_notional / PAPER_CAPITAL_INR * remaining_fraction

    confidence = _safe_number(_value(trade, "confidence"))
    if confidence is not None:
        return build_inr_paper_sizing(confidence)["allocation_percent"] / 100

    entry = _safe_number(_value(trade, "entry_price"))
    stop_loss = _safe_number(_value(trade, "stop_loss"))
    risk_percent = _safe_number(_value(trade, "risk_percent"))
    if (
        entry is None
        or stop_loss is None
        or risk_percent is None
        or entry <= 0
        or risk_percent < 0
    ):
        return None
    stop_distance_percent = abs(entry - stop_loss) / entry * 100
    if stop_distance_percent <= 0:
        return None
    return risk_percent / stop_distance_percent


def _value(record, name):
    if isinstance(record, dict):
        return record.get(name)
    return getattr(record, name, None)


def _safe_number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _timestamp(value):
    if isinstance(value, datetime):
        return _naive_utc(value)
    if not value:
        return None
    try:
        return _naive_utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except ValueError:
        return None


def _naive_utc(value):
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value
