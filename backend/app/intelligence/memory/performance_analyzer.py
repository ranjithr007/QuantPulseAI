class PerformanceAnalyzer:

    def analyze(self, trades):

        wins = [x for x in trades if x.result == "WIN"]

        winrate = (len(wins) / len(trades)) * 100

        return {"total_trades": len(trades), "win_rate": round(winrate, 2)}
