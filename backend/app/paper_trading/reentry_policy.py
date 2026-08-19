from datetime import datetime, timedelta, timezone

from app.utils.freshness import normalize_timestamp_to_utc


PAPER_STOP_REENTRY_COOLDOWN_MINUTES = 30


def same_side_stop_reentry_cooldown(trades, symbol, side, now=None):
    """Return the active same-side cooldown following a stop-loss exit."""
    normalized_symbol = str(symbol or "").strip().upper()
    normalized_side = str(side or "").strip().upper()
    current_time = normalize_timestamp_to_utc(now or datetime.now(timezone.utc))

    stopped_trades = []
    for trade in trades or []:
        if str(_value(trade, "symbol") or "").strip().upper() != normalized_symbol:
            continue
        if str(_value(trade, "side") or "").strip().upper() != normalized_side:
            continue
        if str(_value(trade, "status") or "").strip().upper() != "CLOSED":
            continue
        if str(_value(trade, "exit_reason") or "").strip().upper() != "STOP":
            continue

        closed_at = normalize_timestamp_to_utc(_value(trade, "closed_at"))
        if closed_at is not None:
            stopped_trades.append((closed_at, trade))

    if not stopped_trades:
        return _cooldown_payload(normalized_symbol, normalized_side)

    stopped_at, stopped_trade = max(stopped_trades, key=lambda item: item[0])
    expires_at = stopped_at + timedelta(minutes=PAPER_STOP_REENTRY_COOLDOWN_MINUTES)
    remaining_seconds = max(0, int((expires_at - current_time).total_seconds()))
    active = current_time < expires_at
    return {
        "active": active,
        "symbol": normalized_symbol,
        "blocked_side": normalized_side,
        "cooldown_minutes": PAPER_STOP_REENTRY_COOLDOWN_MINUTES,
        "remaining_seconds": remaining_seconds if active else 0,
        "stopped_trade_id": _value(stopped_trade, "id"),
        "stopped_at": stopped_at,
        "expires_at": expires_at,
    }


def _cooldown_payload(symbol, side):
    return {
        "active": False,
        "symbol": symbol,
        "blocked_side": side,
        "cooldown_minutes": PAPER_STOP_REENTRY_COOLDOWN_MINUTES,
        "remaining_seconds": 0,
        "stopped_trade_id": None,
        "stopped_at": None,
        "expires_at": None,
    }


def _value(record, key):
    if isinstance(record, dict):
        return record.get(key)
    return getattr(record, key, None)
