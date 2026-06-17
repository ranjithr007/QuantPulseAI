class DrawdownEngine:
    def calculate(self, equity_high, current_equity):
        if equity_high is None or current_equity is None or equity_high <= 0:
            return {
                "drawdown_percent": 0,
                "risk_state": "UNKNOWN",
            }

        drawdown = ((equity_high - current_equity) / equity_high) * 100

        if drawdown >= 15:
            state = "SYSTEM_PAUSE"
        elif drawdown >= 8:
            state = "HALT_NEW_ENTRIES"
        elif drawdown >= 5:
            state = "REDUCE_POSITION_SIZE"
        else:
            state = "NORMAL"

        return {
            "drawdown_percent": round(max(drawdown, 0), 2),
            "risk_state": state,
        }
