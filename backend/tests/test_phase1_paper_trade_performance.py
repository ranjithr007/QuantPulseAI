import unittest
from types import SimpleNamespace

from app.paper_trading.paper_trade_performance import paper_trade_performance


class Phase1PaperTradePerformanceTests(unittest.TestCase):
    def test_performance_handles_empty_history(self):
        result = paper_trade_performance([])

        self.assertEqual(result["total_trades"], 0)
        self.assertEqual(result["win_rate"], 0)
        self.assertEqual(result["average_pnl_percent"], 0)
        self.assertEqual(result["average_win_pnl_percent"], 0)
        self.assertEqual(result["average_loss_pnl_percent"], 0)
        self.assertEqual(result["total_pnl_percent"], 0)
        self.assertEqual(result["edge_health"]["status"], "NO_CLOSED_TRADES")
        self.assertIsNone(result["edge_health"]["profit_factor"])

    def test_performance_calculates_closed_trade_scorecard(self):
        trades = [
            SimpleNamespace(
                status="CLOSED",
                result="WIN",
                pnl_percent=2.5,
                side="LONG",
            ),
            SimpleNamespace(
                status="CLOSED",
                result="LOSS",
                pnl_percent=-1.0,
                side="SHORT",
            ),
            SimpleNamespace(
                status="OPEN",
                result=None,
                pnl_percent=None,
                side="LONG",
            ),
        ]

        result = paper_trade_performance(trades)

        self.assertEqual(result["total_trades"], 3)
        self.assertEqual(result["open_trades"], 1)
        self.assertEqual(result["closed_trades"], 2)
        self.assertEqual(result["wins"], 1)
        self.assertEqual(result["losses"], 1)
        self.assertEqual(result["long_trades"], 2)
        self.assertEqual(result["short_trades"], 1)
        self.assertEqual(result["win_rate"], 50.0)
        self.assertEqual(result["average_pnl_percent"], 0.75)
        self.assertEqual(result["average_win_pnl_percent"], 2.5)
        self.assertEqual(result["average_loss_pnl_percent"], -1.0)
        self.assertEqual(result["total_pnl_percent"], 1.5)
        self.assertEqual(result["edge_health"]["status"], "POSITIVE")
        self.assertEqual(result["edge_health"]["profit_factor"], 2.5)
        self.assertEqual(result["edge_health"]["payoff_ratio"], 2.5)
        self.assertEqual(result["edge_health"]["breakeven_win_rate_percent"], 28.57)
        self.assertEqual(result["edge_health"]["profitable_win_rate_percent"], 50.0)
        self.assertEqual(result["edge_health"]["win_rate_gap_percent"], 21.43)
        self.assertEqual(result["edge_health"]["expectancy_percent"], 0.75)


if __name__ == "__main__":
    unittest.main()
