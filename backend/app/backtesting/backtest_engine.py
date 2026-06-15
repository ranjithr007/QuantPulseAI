
def run_backtest(candles, signal, stop_percent=1, target_percent=2):

    wins = 0
    losses = 0

    profit = 0

    trades = []

    for candle in candles:

        entry = candle.close_price

        if signal == "LONG":

            stop = entry * (1 - stop_percent / 100)

            target = entry * (1 + target_percent / 100)

        else:

            stop = entry * (1 + stop_percent / 100)

            target = entry * (1 - target_percent / 100)

        result = None

        if signal == "LONG":

            if candle.high_price >= target:

                result = "WIN"

                pnl = target - entry

            elif candle.low_price <= stop:

                result = "LOSS"

                pnl = stop - entry

        if signal == "SHORT":

            if candle.low_price <= target:

                result = "WIN"

                pnl = entry - target

            elif candle.high_price >= stop:

                result = "LOSS"

                pnl = entry - stop

        if result:

            if result == "WIN":
                wins += 1

            else:
                losses += 1

            profit += pnl

            trades.append(
                {
                    "entry": entry,
                    "target": target,
                    "stop": stop,
                    "result": result,
                    "pnl": pnl,
                }
            )

    total = wins + losses

    return {
        "total_trades": total,
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / total * 100, 2) if total else 0,
        "profit": round(profit, 2),
        "trades": trades,
    }