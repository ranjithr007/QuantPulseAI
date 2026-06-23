import unittest
from pathlib import Path
from types import SimpleNamespace

from app.paper_trading.paper_trade_monitor import evaluate_paper_trade_exit
from app.scheduler.registry import get_job_definition
from app.scheduler.registry import resolve_job_ids


PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = PROJECT_ROOT / "backend" / "app"


class Phase1PaperTradeMonitorTests(unittest.TestCase):
    def test_long_trade_closes_win_when_target_hit(self):
        trade = SimpleNamespace(
            id=1,
            symbol="BTCUSDT",
            side="LONG",
            stop_loss=99.0,
            target1=102.0,
        )
        candle = SimpleNamespace(
            high_price=102.5,
            low_price=100.0,
            candle_time=None,
        )

        result = evaluate_paper_trade_exit(trade, candle)

        self.assertEqual(result["action"], "CLOSE")
        self.assertEqual(result["result"], "WIN")
        self.assertEqual(result["exit_price"], 101.94)
        self.assertIn("fill_profile", result)
        self.assertEqual(result["fill_profile"]["trigger_type"], "TARGET")

    def test_long_trade_closes_loss_before_win_when_both_hit(self):
        trade = SimpleNamespace(
            id=1,
            symbol="BTCUSDT",
            side="LONG",
            stop_loss=99.0,
            target1=102.0,
        )
        candle = SimpleNamespace(
            high_price=102.5,
            low_price=98.5,
            candle_time=None,
        )

        result = evaluate_paper_trade_exit(trade, candle)

        self.assertEqual(result["action"], "CLOSE")
        self.assertEqual(result["result"], "LOSS")
        self.assertEqual(result["exit_price"], 98.9505)
        self.assertIn("fill_profile", result)
        self.assertEqual(result["fill_profile"]["trigger_type"], "STOP")

    def test_short_trade_closes_win_when_target_hit(self):
        trade = SimpleNamespace(
            id=1,
            symbol="BTCUSDT",
            side="SHORT",
            stop_loss=101.0,
            target1=98.0,
        )
        candle = SimpleNamespace(
            high_price=100.0,
            low_price=97.5,
            candle_time=None,
        )

        result = evaluate_paper_trade_exit(trade, candle)

        self.assertEqual(result["action"], "CLOSE")
        self.assertEqual(result["result"], "WIN")
        self.assertEqual(result["exit_price"], 98.0595)
        self.assertIn("fill_profile", result)
        self.assertEqual(result["fill_profile"]["trigger_type"], "TARGET")

    def test_trade_holds_when_no_level_hit(self):
        trade = SimpleNamespace(
            id=1,
            symbol="BTCUSDT",
            side="LONG",
            stop_loss=99.0,
            target1=102.0,
        )
        candle = SimpleNamespace(
            high_price=101.0,
            low_price=100.0,
            candle_time=None,
        )

        result = evaluate_paper_trade_exit(trade, candle)

        self.assertEqual(result["action"], "HOLD")
        self.assertEqual(result["result"], "OPEN")

    def test_paper_trade_monitor_job_is_registered(self):
        job = get_job_definition("paper-trade-monitor")

        self.assertIsNotNone(job)
        self.assertEqual(job.id, "paper_trade_monitor")
        self.assertEqual(job.module, "app.jobs.paper_trade_monitor_job")
        self.assertEqual(job.function, "run_paper_trade_monitor_job")
        self.assertEqual(job.seconds, 60)
        self.assertEqual(
            resolve_job_ids(["paper-trade-monitor"]),
            ["paper_trade_monitor"],
        )

    def test_paper_trade_execute_job_is_registered(self):
        job = get_job_definition("paper-trade-execute")

        self.assertIsNotNone(job)
        self.assertEqual(job.id, "paper_trade_execute")
        self.assertEqual(job.module, "app.jobs.paper_trade_execute_job")
        self.assertEqual(job.function, "run_paper_trade_execute_job")
        self.assertEqual(job.seconds, 60)
        self.assertEqual(
            resolve_job_ids(["paper-trade-execute"]),
            ["paper_trade_execute"],
        )

    def test_paper_trade_execute_job_reuses_api_execution_core(self):
        source = (APP_ROOT / "jobs" / "paper_trade_execute_job.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("execute_paper_trade_candidates_for_symbol", source)
        self.assertIn("def run_paper_trade_execute_job", source)

    def test_paper_trade_repository_can_close_trade(self):
        source = (APP_ROOT / "repositories" / "paper_trade_repository.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("def close_trade", source)
        self.assertIn('trade.status = "CLOSED"', source)
        self.assertIn("trade.exit_price = exit_price", source)
        self.assertIn("trade.gross_pnl_percent = round(gross_pnl, 4)", source)
        self.assertIn("trade.fees_percent = round(fees_percent, 4)", source)
        self.assertIn("trade.pnl_percent = round(gross_pnl - fees_percent, 4)", source)
        self.assertIn("trade.closed_at = datetime.utcnow()", source)


if __name__ == "__main__":
    unittest.main()
