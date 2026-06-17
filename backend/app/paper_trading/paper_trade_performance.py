def paper_trade_performance(trades):
    total = len(trades)
    open_trades = [
        trade
        for trade in trades
        if trade.status == "OPEN"
    ]
    closed_trades = [
        trade
        for trade in trades
        if trade.status == "CLOSED"
    ]
    wins = [
        trade
        for trade in closed_trades
        if trade.result == "WIN"
    ]
    losses = [
        trade
        for trade in closed_trades
        if trade.result == "LOSS"
    ]
    pnl_values = [
        float(trade.pnl_percent)
        for trade in closed_trades
        if trade.pnl_percent is not None
    ]
    closed_count = len(closed_trades)

    return {
        "total_trades": total,
        "open_trades": len(open_trades),
        "closed_trades": closed_count,
        "wins": len(wins),
        "losses": len(losses),
        "long_trades": sum(1 for trade in trades if trade.side == "LONG"),
        "short_trades": sum(1 for trade in trades if trade.side == "SHORT"),
        "win_rate": round((len(wins) / closed_count) * 100, 2)
        if closed_count
        else 0,
        "average_pnl_percent": round(sum(pnl_values) / len(pnl_values), 2)
        if pnl_values
        else 0,
        "total_pnl_percent": round(sum(pnl_values), 2),
    }
