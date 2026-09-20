from datetime import timedelta

from app.paper_trading.fill_model import simulate_exit_fill
from app.paper_trading.exit_policy import PAPER_TARGET1_FRACTION
from app.paper_trading.exit_policy import is_staged_exit_policy
from app.paper_trading.exit_policy import target1_protection_stop
from app.paper_trading.exit_policy import target2_trail_trigger
from app.paper_trading.exit_evidence import exit_context
from app.paper_trading.exit_evidence import read_evidence


COST_SAFE_PROTECTION_PROFILE = "COST_SAFE_PROTECTION_1R_V1"
DEFAULT_LOCKED_PROFIT_FRACTION = 0.5


def evaluate_paper_trade_exit(trade, candle):
    high = float(candle.high_price)
    low = float(candle.low_price)

    if is_staged_exit_policy(getattr(trade, "exit_policy", None)):
        return _evaluate_staged_exit(trade, candle, high, low)

    if trade.side == "LONG":
        stop_hit = low <= trade.stop_loss
        target_hit = high >= trade.target1
    else:
        stop_hit = high >= trade.stop_loss
        target_hit = low <= trade.target1

    if stop_hit:
        exit_fill = simulate_exit_fill(
            trade,
            _stop_trigger_price(trade, candle, high, low),
            trigger_type="STOP",
        )
        return _exit_decision(
            trade,
            candle,
            "LOSS",
            exit_fill["exit_fill_price"],
            exit_fill,
        )

    if target_hit:
        exit_fill = simulate_exit_fill(trade, trade.target1, trigger_type="TARGET")
        return _exit_decision(
            trade,
            candle,
            "WIN",
            exit_fill["exit_fill_price"],
            exit_fill,
        )

    return {
        "paper_trade_id": trade.id,
        "symbol": trade.symbol,
        "side": trade.side,
        "action": "HOLD",
        "result": "OPEN",
        "candle_time": candle.candle_time,
        "high_price": high,
        "low_price": low,
    }


def _evaluate_staged_exit(trade, candle, high, low):
    target1_complete = getattr(trade, "target1_hit_at", None) is not None
    target_price = trade.target2 if target1_complete else trade.target1

    if _maximum_hold_reached(trade, candle):
        return _time_exit_decision(trade, candle)

    if trade.side == "LONG":
        # Inclusive safety boundary: a LONG exits when the observed price is
        # equal to or below its active stop (including break-even after T1).
        stop_hit = low <= trade.stop_loss
        target_hit = high >= target_price
    else:
        # Inclusive inverse boundary: a SHORT exits when the observed price is
        # equal to or above its active stop (including break-even after T1).
        stop_hit = high >= trade.stop_loss
        target_hit = low <= target_price

    # A candle with both levels touched is resolved conservatively at the stop.
    if stop_hit:
        exit_fill = simulate_exit_fill(
            trade,
            _stop_trigger_price(trade, candle, high, low),
            trigger_type="STOP",
        )
        return _exit_decision(
            trade,
            candle,
            "WIN" if target1_complete else "LOSS",
            exit_fill["exit_fill_price"],
            exit_fill,
        )

    if target_hit and not target1_complete:
        exit_fill = simulate_exit_fill(trade, trade.target1, trigger_type="TARGET1")
        target1_fraction = _target1_fraction(trade)
        return {
            "paper_trade_id": trade.id,
            "symbol": trade.symbol,
            "side": trade.side,
            "action": "PARTIAL_CLOSE",
            "result": "OPEN",
            "exit_price": exit_fill["exit_fill_price"],
            "fill_profile": exit_fill,
            "remaining_position_fraction": 1.0 - target1_fraction,
            "new_stop_loss": target1_protection_stop(
                trade.side,
                trade.entry_price,
                trade.target1,
            ),
            "candle_time": getattr(candle, "close_time", None) or candle.candle_time,
            "high_price": high,
            "low_price": low,
        }

    if target_hit:
        exit_fill = simulate_exit_fill(trade, trade.target2, trigger_type="TARGET2")
        return _exit_decision(
            trade,
            candle,
            "WIN",
            exit_fill["exit_fill_price"],
            exit_fill,
        )

    if target1_complete:
        trail_trigger = target2_trail_trigger(trade.target1, trade.target2)
        if trade.side == "LONG":
            trail_trigger_hit = high >= trail_trigger
            target1_stop_active = float(trade.stop_loss) >= float(trade.target1)
        else:
            trail_trigger_hit = low <= trail_trigger
            target1_stop_active = float(trade.stop_loss) <= float(trade.target1)
        if trail_trigger_hit and not target1_stop_active:
            return {
                "paper_trade_id": trade.id,
                "symbol": trade.symbol,
                "side": trade.side,
                "action": "MOVE_STOP",
                "result": "OPEN",
                "new_stop_loss": float(trade.target1),
                "reason": "TARGET2_75_PERCENT_PROGRESS",
                "trail_trigger_price": trail_trigger,
                "candle_time": candle.candle_time,
                "high_price": high,
                "low_price": low,
            }

    trailing_stop = (
        _cost_safe_profit_protection_stop(trade, candle)
        if _uses_cost_safe_protection(trade)
        else _favorable_price_trailing_stop(trade, candle)
    )
    if trailing_stop is not None:
        current_stop = float(trade.stop_loss)
        improves_protection = (
            trailing_stop > current_stop
            if str(trade.side).upper() == "LONG"
            else trailing_stop < current_stop
        )
        if improves_protection:
            return {
                "paper_trade_id": trade.id,
                "symbol": trade.symbol,
                "side": trade.side,
                "action": "MOVE_STOP",
                "result": "OPEN",
                "new_stop_loss": trailing_stop,
                "reason": "FAVORABLE_PRICE_TRAIL",
                "favorable_move_points": round(
                    abs(
                        float(getattr(candle, "close_price"))
                        - float(trade.entry_price)
                    ),
                    _price_precision(trade.entry_price),
                ),
                "candle_time": candle.candle_time,
                "high_price": high,
                "low_price": low,
            }

    if _maximum_hold_reached(trade, candle):
        return _time_exit_decision(trade, candle)

    return {
        "paper_trade_id": trade.id,
        "symbol": trade.symbol,
        "side": trade.side,
        "action": "HOLD",
        "result": "OPEN",
        "candle_time": candle.candle_time,
        "high_price": high,
        "low_price": low,
        "target1_complete": target1_complete,
    }


def _stop_trigger_price(trade, candle, high, low):
    """Use the observed mark when it has already crossed through the stop."""

    stop_loss = float(trade.stop_loss)
    if not getattr(candle, "live_mark", False):
        return stop_loss
    if trade.side == "LONG":
        return min(stop_loss, low)
    return max(stop_loss, high)


def _target1_fraction(trade):
    persisted = getattr(trade, "target1_fraction", None)
    return float(PAPER_TARGET1_FRACTION if persisted is None else persisted)


def _favorable_price_trailing_stop(trade, candle):
    """Move the original stop one-for-one with favorable observed price movement."""
    initial_stop = getattr(trade, "initial_stop_loss", None)
    close_price = getattr(candle, "close_price", None)
    if initial_stop is None or close_price is None:
        return None

    entry = float(trade.entry_price)
    close = float(close_price)
    initial = float(initial_stop)
    activation_r = float(getattr(trade, "trailing_activation_r", None) or 0)
    favorable = close - entry if str(trade.side).upper() == "LONG" else entry - close
    # New rows persist an explicit activation. NULL legacy rows retain their
    # historical immediate one-for-one behavior for replay compatibility.
    if activation_r > 0 and favorable < abs(entry - initial) * activation_r:
        return None
    precision = _price_precision(entry)
    if str(trade.side).upper() == "LONG":
        favorable_move = max(0.0, close - entry)
        return round(initial + favorable_move, precision)

    favorable_move = max(0.0, entry - close)
    return round(initial - favorable_move, precision)


def _uses_cost_safe_protection(trade):
    evidence = read_evidence(getattr(trade, "execution_evidence_json", None))
    return evidence.get("exit_management_profile") == COST_SAFE_PROTECTION_PROFILE


def _cost_safe_profit_protection_stop(trade, candle):
    """Lock half of the favorable move after the configured one-R activation.

    This keeps the candidate's original hard stop until activation, then moves
    the stop at half the favorable pace. It preserves the existing staged T1/T2
    rules while avoiding the baseline's one-for-one giveback behavior.
    """
    initial_stop = getattr(trade, "initial_stop_loss", None)
    close_price = getattr(candle, "close_price", None)
    if initial_stop is None or close_price is None:
        return None

    entry = float(trade.entry_price)
    initial = float(initial_stop)
    close = float(close_price)
    side = str(trade.side).upper()
    sign = 1 if side == "LONG" else -1
    favorable = sign * (close - entry)
    risk = abs(entry - initial)
    activation_r = float(getattr(trade, "trailing_activation_r", None) or 0)
    if risk <= 0 or activation_r <= 0 or favorable < risk * activation_r:
        return None

    evidence = read_evidence(getattr(trade, "execution_evidence_json", None))
    try:
        locked_fraction = float(
            evidence.get("locked_profit_fraction", DEFAULT_LOCKED_PROFIT_FRACTION)
        )
    except (TypeError, ValueError):
        locked_fraction = DEFAULT_LOCKED_PROFIT_FRACTION
    if not 0 < locked_fraction < 1:
        locked_fraction = DEFAULT_LOCKED_PROFIT_FRACTION

    protected_move = favorable * locked_fraction
    precision = _price_precision(entry)
    return round(entry + sign * protected_move, precision)


def _price_precision(price):
    price = abs(float(price))
    if price < 1:
        return 6
    if price < 10:
        return 5
    if price < 100:
        return 4
    return 2


def _maximum_hold_reached(trade, candle):
    opened_at = getattr(trade, "opened_at", None)
    candle_time = (
        getattr(candle, "close_time", None)
        or getattr(candle, "candle_time", None)
    )
    max_hold_hours = getattr(trade, "max_hold_hours", None)
    if opened_at is None or candle_time is None or not max_hold_hours:
        return False

    # SQLAlchemy can return either naive or timezone-aware datetimes. Compare
    # like with like without changing the recorded wall-clock values.
    if getattr(opened_at, "tzinfo", None) is None and getattr(candle_time, "tzinfo", None):
        candle_time = candle_time.replace(tzinfo=None)
    elif getattr(opened_at, "tzinfo", None) and getattr(candle_time, "tzinfo", None) is None:
        opened_at = opened_at.replace(tzinfo=None)
    return candle_time >= opened_at + timedelta(hours=float(max_hold_hours))


def _time_exit_decision(trade, candle):
    close_price = float(getattr(candle, "close_price", trade.entry_price))
    exit_fill = simulate_exit_fill(trade, close_price, trigger_type="TIME_EXIT")
    return _exit_decision(
        trade,
        candle,
        "TIME_EXIT",
        exit_fill["exit_fill_price"],
        exit_fill,
    )


def _exit_decision(trade, candle, result, exit_price, fill_profile=None):
    fill_profile = dict(fill_profile or {})
    fill_profile["exit_evidence_at"] = getattr(candle, "close_time", None) or candle.candle_time
    fill_profile["exit_evidence"] = exit_context(trade, candle, fill_profile.get("trigger_type", "UNKNOWN"))
    return {
        "paper_trade_id": trade.id,
        "symbol": trade.symbol,
        "side": trade.side,
        "action": "CLOSE",
        "result": result,
        "exit_price": exit_price,
        "fill_profile": fill_profile,
        "candle_time": candle.candle_time,
        "high_price": float(candle.high_price),
        "low_price": float(candle.low_price),
    }
