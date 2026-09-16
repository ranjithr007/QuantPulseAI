from app.paper_trading.evidence_scope import production_paper_trade_records


def performance_edge_metrics(
    *,
    gross_profit_percent,
    gross_loss_percent,
    profitable_trades,
    losing_trades,
    closed_trades,
):
    gross_profit = max(0.0, float(gross_profit_percent or 0.0))
    gross_loss = min(0.0, float(gross_loss_percent or 0.0))
    profit_count = max(0, int(profitable_trades or 0))
    loss_count = max(0, int(losing_trades or 0))
    closed_count = max(0, int(closed_trades or 0))
    average_win = gross_profit / profit_count if profit_count else 0.0
    average_loss = gross_loss / loss_count if loss_count else 0.0
    loss_magnitude = abs(gross_loss)
    average_loss_magnitude = abs(average_loss)
    profit_factor = gross_profit / loss_magnitude if loss_magnitude else None
    payoff_ratio = (
        average_win / average_loss_magnitude
        if average_loss_magnitude
        else None
    )
    breakeven_denominator = average_win + average_loss_magnitude
    breakeven_win_rate = (
        average_loss_magnitude / breakeven_denominator * 100
        if breakeven_denominator
        else None
    )
    profitable_win_rate = (
        profit_count / closed_count * 100
        if closed_count
        else 0.0
    )
    expectancy = (
        (gross_profit + gross_loss) / closed_count
        if closed_count
        else 0.0
    )
    win_rate_gap = (
        profitable_win_rate - breakeven_win_rate
        if breakeven_win_rate is not None
        else None
    )
    if not closed_count:
        status = "NO_CLOSED_TRADES"
    elif expectancy > 0:
        status = "POSITIVE"
    elif expectancy < 0:
        status = "NEGATIVE"
    else:
        status = "FLAT"

    return {
        "status": status,
        "gross_profit_percent": round(gross_profit, 2),
        "gross_loss_percent": round(gross_loss, 2),
        "profitable_trades": profit_count,
        "losing_pnl_trades": loss_count,
        "average_win_pnl_percent": round(average_win, 2),
        "average_loss_pnl_percent": round(average_loss, 2),
        "expectancy_percent": round(expectancy, 2),
        "profit_factor": round(profit_factor, 3) if profit_factor is not None else None,
        "payoff_ratio": round(payoff_ratio, 3) if payoff_ratio is not None else None,
        "breakeven_win_rate_percent": (
            round(breakeven_win_rate, 2)
            if breakeven_win_rate is not None
            else None
        ),
        "profitable_win_rate_percent": round(profitable_win_rate, 2),
        "win_rate_gap_percent": (
            round(win_rate_gap, 2)
            if win_rate_gap is not None
            else None
        ),
    }


def paper_trade_performance(trades):
    trades = production_paper_trade_records(trades)
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
    winning_pnl_values = [value for value in pnl_values if value > 0]
    losing_pnl_values = [value for value in pnl_values if value < 0]
    closed_count = len(closed_trades)
    edge_health = performance_edge_metrics(
        gross_profit_percent=sum(winning_pnl_values),
        gross_loss_percent=sum(losing_pnl_values),
        profitable_trades=len(winning_pnl_values),
        losing_trades=len(losing_pnl_values),
        closed_trades=closed_count,
    )

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
        "average_win_pnl_percent": edge_health["average_win_pnl_percent"],
        "average_loss_pnl_percent": edge_health["average_loss_pnl_percent"],
        "edge_health": edge_health,
        "total_pnl_percent": round(sum(pnl_values), 2),
    }
