from datetime import timedelta

from app.paper_trading.fill_model import simulate_exit_fill
from app.paper_trading.exit_policy import is_staged_exit_policy


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
        exit_fill = simulate_exit_fill(trade, trade.stop_loss, trigger_type="STOP")
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

    if trade.side == "LONG":
        stop_hit = low <= trade.stop_loss
        target_hit = high >= target_price
    else:
        stop_hit = high >= trade.stop_loss
        target_hit = low <= target_price

    # A candle with both levels touched is resolved conservatively at the stop.
    if stop_hit:
        exit_fill = simulate_exit_fill(trade, trade.stop_loss, trigger_type="STOP")
        return _exit_decision(
            trade,
            candle,
            "WIN" if target1_complete else "LOSS",
            exit_fill["exit_fill_price"],
            exit_fill,
        )

    if target_hit and not target1_complete:
        exit_fill = simulate_exit_fill(trade, trade.target1, trigger_type="TARGET1")
        return {
            "paper_trade_id": trade.id,
            "symbol": trade.symbol,
            "side": trade.side,
            "action": "PARTIAL_CLOSE",
            "result": "OPEN",
            "exit_price": exit_fill["exit_fill_price"],
            "fill_profile": exit_fill,
            "remaining_position_fraction": 1.0
            - float(getattr(trade, "target1_fraction", None) or 0.5),
            "new_stop_loss": float(trade.entry_price),
            "candle_time": candle.candle_time,
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

    if _maximum_hold_reached(trade, candle):
        close_price = float(getattr(candle, "close_price", trade.entry_price))
        exit_fill = simulate_exit_fill(trade, close_price, trigger_type="TIME_EXIT")
        return _exit_decision(
            trade,
            candle,
            "TIME_EXIT",
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
        "target1_complete": target1_complete,
    }


def _maximum_hold_reached(trade, candle):
    opened_at = getattr(trade, "opened_at", None)
    candle_time = getattr(candle, "candle_time", None)
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


def _exit_decision(trade, candle, result, exit_price, fill_profile=None):
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
