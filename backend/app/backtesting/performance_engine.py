from math import sqrt
from statistics import mean
from statistics import stdev


def calculate_performance(
    trades,
    initial_capital=None,
    final_capital=None,
    equity_curve=None,
):
    trades = list(trades or [])
    wins = [trade for trade in trades if float(trade.get("pnl", 0) or 0) > 0]
    losses = [trade for trade in trades if float(trade.get("pnl", 0) or 0) < 0]
    gross_profit = sum(float(trade.get("pnl", 0) or 0) for trade in wins)
    gross_loss = abs(sum(float(trade.get("pnl", 0) or 0) for trade in losses))
    net_profit = sum(float(trade.get("pnl", 0) or 0) for trade in trades)
    returns = [float(trade.get("pnl_percent", 0) or 0) for trade in trades]
    profit_factor = gross_profit / gross_loss if gross_loss else None
    win_rate = (len(wins) / len(trades)) * 100 if trades else 0
    expectancy = mean(returns) if returns else 0
    return_std = stdev(returns) if len(returns) > 1 else 0
    trade_sharpe = (mean(returns) / return_std) * sqrt(len(returns)) if return_std else 0
    max_drawdown, max_drawdown_percent = _max_drawdown(
        equity_curve or [],
        initial_capital,
    )
    consecutive_wins, consecutive_losses = _streaks(trades)
    total_return_percent = 0
    if initial_capital and final_capital is not None:
        total_return_percent = ((float(final_capital) - float(initial_capital)) / float(initial_capital)) * 100

    return {
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": len(trades) - len(wins) - len(losses),
        "win_rate": round(win_rate, 2),
        "profit": round(net_profit, 2),
        "net_profit": round(net_profit, 2),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "profit_factor": round(profit_factor, 2) if profit_factor is not None else None,
        "expectancy_percent": round(expectancy, 4),
        "sharpe_ratio": round(trade_sharpe, 4),
        "max_drawdown": round(max_drawdown, 2),
        "max_drawdown_percent": round(max_drawdown_percent, 4),
        "max_consecutive_wins": consecutive_wins,
        "max_consecutive_losses": consecutive_losses,
        "initial_capital": round(float(initial_capital), 2) if initial_capital is not None else None,
        "final_capital": round(float(final_capital), 2) if final_capital is not None else None,
        "total_return_percent": round(total_return_percent, 4),
        "fees_paid": round(sum(float(trade.get("fees", 0) or 0) for trade in trades), 2),
    }


def _max_drawdown(equity_curve, initial_capital):
    values = [float(point.get("equity", 0) or 0) for point in equity_curve]
    if not values and initial_capital is not None:
        values = [float(initial_capital)]
    if not values:
        return 0, 0

    peak = values[0]
    max_amount = 0
    max_percent = 0
    for value in values:
        peak = max(peak, value)
        drawdown = peak - value
        drawdown_percent = (drawdown / peak) * 100 if peak else 0
        max_amount = max(max_amount, drawdown)
        max_percent = max(max_percent, drawdown_percent)
    return max_amount, max_percent


def _streaks(trades):
    best_wins = 0
    best_losses = 0
    wins = 0
    losses = 0

    for trade in trades:
        pnl = float(trade.get("pnl", 0) or 0)
        if pnl > 0:
            wins += 1
            losses = 0
        elif pnl < 0:
            losses += 1
            wins = 0
        else:
            wins = 0
            losses = 0
        best_wins = max(best_wins, wins)
        best_losses = max(best_losses, losses)

    return best_wins, best_losses
