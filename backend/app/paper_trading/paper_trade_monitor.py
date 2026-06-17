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
        return _exit_decision(trade, candle, "LOSS", trade.stop_loss)

    if target_hit:
        return _exit_decision(trade, candle, "WIN", trade.target1)

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


def _exit_decision(trade, candle, result, exit_price):
    return {
        "paper_trade_id": trade.id,
        "symbol": trade.symbol,
        "side": trade.side,
        "action": "CLOSE",
        "result": result,
        "exit_price": exit_price,
        "candle_time": candle.candle_time,
        "high_price": float(candle.high_price),
        "low_price": float(candle.low_price),
    }
