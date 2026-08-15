import unittest
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.jobs.paper_trade_monitor_job import run_paper_trade_monitor_job
from app.paper_trading.paper_trade_monitor import evaluate_paper_trade_exit
from app.scheduler.registry import get_job_definition
from app.scheduler.registry import resolve_job_ids


PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = PROJECT_ROOT / "backend" / "app"


class Phase1PaperTradeMonitorTests(unittest.TestCase):
    def _staged_trade(self, **overrides):
        values = {
            "id": 1,
            "symbol": "BTCUSDT",
            "side": "SHORT",
            "entry_price": 100.0,
            "stop_loss": 100.75,
            "target1": 98.5,
            "target2": 97.7,
            "confidence": 50,
            "risk_reward": 2.0,
            "exit_policy": "PAPER_STAGED_EXIT_V1",
            "target1_fraction": 0.5,
            "target1_hit_at": None,
            "max_hold_hours": 48,
            "opened_at": datetime(2026, 8, 10, 0, 0),
        }
        values.update(overrides)
        return SimpleNamespace(**values)

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
        self.assertEqual(result["exit_price"], 101.95)
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
        self.assertEqual(result["exit_price"], 98.0496)
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

    def test_staged_trade_partially_closes_at_target1_and_moves_stop(self):
        trade = self._staged_trade()
        candle = SimpleNamespace(
            high_price=100.2,
            low_price=98.4,
            close_price=98.8,
            candle_time=datetime(2026, 8, 10, 4, 0),
        )

        result = evaluate_paper_trade_exit(trade, candle)

        self.assertEqual(result["action"], "PARTIAL_CLOSE")
        self.assertEqual(result["result"], "OPEN")
        self.assertEqual(result["remaining_position_fraction"], 0.5)
        self.assertEqual(result["new_stop_loss"], 100.0)
        self.assertEqual(result["fill_profile"]["trigger_type"], "TARGET1")

    def test_legacy_btc_policy_name_still_uses_staged_lifecycle(self):
        trade = self._staged_trade(exit_policy="BTC_1H_STAGED_V1")
        candle = SimpleNamespace(
            high_price=100.2,
            low_price=98.4,
            close_price=98.8,
            candle_time=datetime(2026, 8, 10, 4, 0),
        )

        result = evaluate_paper_trade_exit(trade, candle)

        self.assertEqual(result["action"], "PARTIAL_CLOSE")
        self.assertEqual(result["remaining_position_fraction"], 0.5)

    def test_staged_trade_closes_remainder_at_target2(self):
        trade = self._staged_trade(
            stop_loss=100.0,
            target1_hit_at=datetime(2026, 8, 10, 4, 0),
        )
        candle = SimpleNamespace(
            high_price=99.0,
            low_price=97.6,
            close_price=97.8,
            candle_time=datetime(2026, 8, 10, 5, 0),
        )

        result = evaluate_paper_trade_exit(trade, candle)

        self.assertEqual(result["action"], "CLOSE")
        self.assertEqual(result["result"], "WIN")
        self.assertEqual(result["fill_profile"]["trigger_type"], "TARGET2")

    def test_staged_trade_closes_at_break_even_after_target1(self):
        trade = self._staged_trade(
            stop_loss=100.0,
            target1_hit_at=datetime(2026, 8, 10, 4, 0),
        )
        candle = SimpleNamespace(
            high_price=100.1,
            low_price=98.0,
            close_price=99.5,
            candle_time=datetime(2026, 8, 10, 5, 0),
        )

        result = evaluate_paper_trade_exit(trade, candle)

        self.assertEqual(result["action"], "CLOSE")
        self.assertEqual(result["result"], "WIN")
        self.assertEqual(result["fill_profile"]["trigger_type"], "STOP")

    def test_staged_trade_time_exits_after_48_hours(self):
        trade = self._staged_trade()
        candle = SimpleNamespace(
            high_price=100.5,
            low_price=99.0,
            close_price=99.4,
            candle_time=trade.opened_at + timedelta(hours=47, minutes=55),
            close_time=trade.opened_at + timedelta(hours=48),
        )

        result = evaluate_paper_trade_exit(trade, candle)

        self.assertEqual(result["action"], "CLOSE")
        self.assertEqual(result["result"], "TIME_EXIT")
        self.assertEqual(result["fill_profile"]["trigger_type"], "TIME_EXIT")

    def test_monitor_replays_missed_five_minute_candles_in_order(self):
        base = datetime(2026, 8, 10, 0, 0)
        trade = self._staged_trade(
            entry_timeframe="4h",
            exit_monitor_timeframe="5m",
            last_exit_evaluated_at=base,
        )
        candles = [
            SimpleNamespace(
                high_price=100.2,
                low_price=99.0,
                close_price=99.5,
                candle_time=base + timedelta(minutes=5),
                open_time=base + timedelta(minutes=5),
                close_time=base + timedelta(minutes=10),
            ),
            SimpleNamespace(
                high_price=100.2,
                low_price=98.4,
                close_price=98.8,
                candle_time=base + timedelta(minutes=10),
                open_time=base + timedelta(minutes=10),
                close_time=base + timedelta(minutes=15),
            ),
            SimpleNamespace(
                high_price=99.0,
                low_price=97.6,
                close_price=97.8,
                candle_time=base + timedelta(minutes=15),
                open_time=base + timedelta(minutes=15),
                close_time=base + timedelta(minutes=20),
            ),
        ]
        fake_db = SimpleNamespace(close=Mock())

        class FakeRepo:
            def get_open_trades(self, db):
                return [trade]

            def ensure_staged_exit_policy(self, db, item):
                return False

            def apply_target1(self, db, item, exit_price, **kwargs):
                item.target1_hit_at = kwargs["candle_time"]
                item.target1_exit_price = exit_price
                item.remaining_position_fraction = 0.5
                item.stop_loss = item.entry_price
                item.last_exit_evaluated_at = kwargs["evaluated_at"]
                return item

            def close_trade(self, db, item, exit_price, result, **kwargs):
                return SimpleNamespace(id=item.id, result="WIN", pnl_percent=2.0)

        with patch(
            "app.jobs.paper_trade_monitor_job.SessionLocal",
            return_value=fake_db,
        ), patch(
            "app.jobs.paper_trade_monitor_job.PaperTradeRepository",
            return_value=FakeRepo(),
        ), patch(
            "app.jobs.paper_trade_monitor_job.get_final_candles_after",
            return_value=candles,
        ):
            summary = run_paper_trade_monitor_job()

        self.assertEqual(summary["candles_evaluated"], 3)
        self.assertEqual(summary["partial_closes"], 1)
        self.assertEqual(summary["closed"], 1)
        self.assertEqual(summary["wins"], 1)
        self.assertEqual(summary["entry_timeframe_fallbacks"], 0)
        self.assertEqual(summary["records"][-1]["monitor_timeframe"], "5m")

    def test_existing_btc_trade_without_policy_keeps_legacy_target1_close(self):
        trade = SimpleNamespace(
            id=35,
            symbol="BTCUSDT",
            side="SHORT",
            stop_loss=105.0,
            target1=90.0,
            target2=85.0,
            exit_policy=None,
        )
        candle = SimpleNamespace(
            high_price=100.0,
            low_price=89.0,
            candle_time=None,
        )

        result = evaluate_paper_trade_exit(trade, candle)

        self.assertEqual(result["action"], "CLOSE")
        self.assertEqual(result["fill_profile"]["trigger_type"], "TARGET")

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
        self.assertIn("trade.funding_cost_percent = round(funding_cost_percent, 6)", source)
        self.assertIn("gross_pnl - fees_percent - funding_cost_percent", source)
        self.assertIn("closed_at = datetime.utcnow()", source)
        self.assertIn("trade.closed_at = closed_at", source)


if __name__ == "__main__":
    unittest.main()
