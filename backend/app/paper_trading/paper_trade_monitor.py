from app.paper_trading.fill_model import simulate_exit_fill


def evaluate_paper_trade_exit(trade, candle):
    high = float(candle.high_price)
    low = float(candle.low_price)

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
