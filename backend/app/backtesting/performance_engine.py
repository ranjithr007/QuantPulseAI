
def calculate_performance(trades):

    gross_profit = sum(t["pnl"] for t in trades if t["result"] == "WIN")

    gross_loss = abs(sum(t["pnl"] for t in trades if t["result"] == "LOSS"))

    profit_factor = gross_profit / gross_loss if gross_loss > 0 else gross_profit

    return {"profit_factor": round(profit_factor, 2)}