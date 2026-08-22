import unittest
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.jobs.paper_trade_monitor_job import _current_mark_candle
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
            "exit_policy": "PAPER_STAGED_EXIT_V2",
            "target1_fraction": 0.75,
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
        self.assertEqual(result["remaining_position_fraction"], 0.25)
        self.assertEqual(result["new_stop_loss"], 99.25)
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
        self.assertEqual(result["remaining_position_fraction"], 0.25)

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

    def test_long_moves_stop_to_target1_at_75_percent_of_t2_path(self):
        trade = self._staged_trade(
            side="LONG",
            entry_price=100.0,
            stop_loss=100.75,
            target1=101.5,
            target2=102.3,
            target1_hit_at=datetime(2026, 8, 10, 4, 0),
        )
        candle = SimpleNamespace(
            high_price=102.1,
            low_price=100.8,
            close_price=102.0,
            candle_time=datetime(2026, 8, 10, 5, 0),
        )

        result = evaluate_paper_trade_exit(trade, candle)

        self.assertEqual("MOVE_STOP", result["action"])
        self.assertEqual(101.5, result["new_stop_loss"])
        self.assertEqual(102.1, result["trail_trigger_price"])
        self.assertEqual("TARGET2_75_PERCENT_PROGRESS", result["reason"])

    def test_short_moves_stop_to_target1_at_75_percent_of_t2_path(self):
        trade = self._staged_trade(
            stop_loss=99.25,
            target1_hit_at=datetime(2026, 8, 10, 4, 0),
        )
        candle = SimpleNamespace(
            high_price=99.2,
            low_price=97.9,
            close_price=98.0,
            candle_time=datetime(2026, 8, 10, 5, 0),
        )

        result = evaluate_paper_trade_exit(trade, candle)

        self.assertEqual("MOVE_STOP", result["action"])
        self.assertEqual(98.5, result["new_stop_loss"])
        self.assertEqual(97.9, result["trail_trigger_price"])

    def test_t2_trailing_stop_waits_until_75_percent_path_is_reached(self):
        trade = self._staged_trade(
            stop_loss=99.25,
            target1_hit_at=datetime(2026, 8, 10, 4, 0),
        )
        candle = SimpleNamespace(
            high_price=99.2,
            low_price=97.91,
            close_price=98.0,
            candle_time=datetime(2026, 8, 10, 5, 0),
        )

        result = evaluate_paper_trade_exit(trade, candle)

        self.assertEqual("HOLD", result["action"])

    def test_monitor_persists_target1_stop_at_t2_progress_milestone(self):
        trade = self._staged_trade(
            stop_loss=99.25,
            target1_hit_at=datetime(2026, 8, 10, 4, 0),
            last_exit_evaluated_at=datetime(2026, 8, 10, 4, 0),
            exit_monitor_timeframe="5m",
        )
        candle = SimpleNamespace(
            high_price=99.2,
            low_price=97.9,
            close_price=98.0,
            candle_time=datetime(2026, 8, 10, 5, 0),
            open_time=datetime(2026, 8, 10, 4, 55),
            close_time=datetime(2026, 8, 10, 5, 0),
        )
        fake_db = SimpleNamespace(close=Mock())

        class FakeRepo:
            def get_open_trades(self, db):
                return [trade]

            def ensure_staged_exit_policy(self, db, item):
                return False

            def move_stop_loss(self, db, item, stop_loss, **kwargs):
                item.stop_loss = stop_loss
                return item

            def mark_exit_evaluated(self, db, item, evaluated_at):
                item.last_exit_evaluated_at = evaluated_at
                return item

        with patch(
            "app.jobs.paper_trade_monitor_job.SessionLocal",
            return_value=fake_db,
        ), patch(
            "app.jobs.paper_trade_monitor_job.PaperTradeRepository",
            return_value=FakeRepo(),
        ), patch(
            "app.jobs.paper_trade_monitor_job.get_final_candles_after",
            return_value=[candle],
        ):
            summary = run_paper_trade_monitor_job()

        self.assertEqual("OK", summary["status"])
        self.assertEqual(1, summary["stop_moves"])
        self.assertEqual(98.5, trade.stop_loss)
        self.assertEqual("MOVE_STOP", summary["records"][0]["action"])

    def test_staged_trade_closes_at_half_target1_profit_stop(self):
        trade = self._staged_trade(
            stop_loss=99.25,
            target1_hit_at=datetime(2026, 8, 10, 4, 0),
        )
        candle = SimpleNamespace(
            high_price=99.25,
            low_price=98.0,
            close_price=99.5,
            candle_time=datetime(2026, 8, 10, 5, 0),
        )

        result = evaluate_paper_trade_exit(trade, candle)

        self.assertEqual(result["action"], "CLOSE")
        self.assertEqual(result["result"], "WIN")
        self.assertEqual(result["fill_profile"]["trigger_type"], "STOP")

    def test_long_live_mark_equal_to_or_below_stop_closes_position(self):
        trade = self._staged_trade(
            side="LONG",
            entry_price=100.0,
            stop_loss=99.25,
            target1=101.5,
            target2=102.3,
        )

        exit_prices = []
        for mark_price in (99.25, 99.0):
            with self.subTest(mark_price=mark_price):
                collector = Mock()
                collector.get_current_mark_price.return_value = {
                    "mark_price": mark_price,
                    "observed_at": datetime(2026, 8, 10, 1, 0),
                    "source": "TEST_CURRENT_MARK",
                }
                candle = _current_mark_candle(trade, collector=collector)

                result = evaluate_paper_trade_exit(trade, candle)

                self.assertEqual(result["action"], "CLOSE")
                self.assertEqual(result["result"], "LOSS")
                self.assertEqual(result["fill_profile"]["trigger_type"], "STOP")
                exit_prices.append(result["exit_price"])

        self.assertLess(exit_prices[1], exit_prices[0])

    def test_long_midpoint_stop_equality_closes_remainder_after_target1(self):
        trade = self._staged_trade(
            side="LONG",
            entry_price=100.0,
            stop_loss=100.75,
            target1=101.5,
            target2=102.3,
            target1_hit_at=datetime(2026, 8, 10, 0, 30),
        )
        candle = SimpleNamespace(
            high_price=100.75,
            low_price=100.75,
            close_price=100.75,
            candle_time=datetime(2026, 8, 10, 1, 0),
            live_mark=True,
        )

        result = evaluate_paper_trade_exit(trade, candle)

        self.assertEqual(result["action"], "CLOSE")
        self.assertEqual(result["result"], "WIN")
        self.assertEqual(result["fill_profile"]["trigger_type"], "STOP")

    def test_short_live_mark_equal_to_or_above_stop_closes_position(self):
        trade = self._staged_trade(
            side="SHORT",
            entry_price=100.0,
            stop_loss=100.75,
            target1=98.5,
            target2=97.7,
        )

        exit_prices = []
        for mark_price in (100.75, 101.0):
            with self.subTest(mark_price=mark_price):
                collector = Mock()
                collector.get_current_mark_price.return_value = {
                    "mark_price": mark_price,
                    "observed_at": datetime(2026, 8, 10, 1, 0),
                    "source": "TEST_CURRENT_MARK",
                }
                candle = _current_mark_candle(trade, collector=collector)

                result = evaluate_paper_trade_exit(trade, candle)

                self.assertEqual(result["action"], "CLOSE")
                self.assertEqual(result["result"], "LOSS")
                self.assertEqual(result["fill_profile"]["trigger_type"], "STOP")
                exit_prices.append(result["exit_price"])

        self.assertGreater(exit_prices[1], exit_prices[0])

    def test_short_midpoint_stop_equality_closes_remainder_after_target1(self):
        trade = self._staged_trade(
            side="SHORT",
            entry_price=100.0,
            stop_loss=99.25,
            target1=98.5,
            target2=97.7,
            target1_hit_at=datetime(2026, 8, 10, 0, 30),
        )
        candle = SimpleNamespace(
            high_price=99.25,
            low_price=99.25,
            close_price=99.25,
            candle_time=datetime(2026, 8, 10, 1, 0),
            live_mark=True,
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

    def test_forced_deadline_catchup_closes_instead_of_partial_target1(self):
        trade = self._staged_trade()
        candle = SimpleNamespace(
            high_price=98.4,
            low_price=98.4,
            close_price=98.4,
            candle_time=trade.opened_at + timedelta(hours=49),
            close_time=trade.opened_at + timedelta(hours=49),
            force_time_exit=True,
        )

        result = evaluate_paper_trade_exit(trade, candle)

        self.assertEqual(result["action"], "CLOSE")
        self.assertEqual(result["result"], "TIME_EXIT")
        self.assertEqual(result["fill_profile"]["trigger_type"], "TIME_EXIT")

    def test_monitor_closes_overdue_trade_from_latest_final_db_candle(self):
        base = datetime(2026, 8, 10, 0, 0)
        trade = self._staged_trade(
            entry_timeframe="1h",
            exit_monitor_timeframe="5m",
            last_exit_evaluated_at=base + timedelta(hours=49),
        )
        latest = SimpleNamespace(
            high_price=100.2,
            low_price=99.0,
            close_price=99.4,
            candle_time=base + timedelta(hours=49),
            open_time=base + timedelta(hours=49),
            close_time=base + timedelta(hours=49, minutes=5),
        )
        fake_db = SimpleNamespace(close=Mock())
        closed = []

        class FakeRepo:
            def get_open_trades(self, db):
                return [trade]

            def ensure_staged_exit_policy(self, db, item):
                return False

            def close_trade(self, db, item, exit_price, result, **kwargs):
                closed.append((exit_price, result, kwargs["fill_profile"]))
                return SimpleNamespace(id=item.id, result="LOSS", pnl_percent=-0.75)

        with patch(
            "app.jobs.paper_trade_monitor_job.SessionLocal",
            return_value=fake_db,
        ), patch(
            "app.jobs.paper_trade_monitor_job.PaperTradeRepository",
            return_value=FakeRepo(),
        ), patch(
            "app.jobs.paper_trade_monitor_job.get_final_candles_after",
            return_value=[],
        ), patch(
            "app.jobs.paper_trade_monitor_job.get_latest_candle",
            return_value=latest,
        ):
            summary = run_paper_trade_monitor_job()

        self.assertEqual(summary["status"], "OK")
        self.assertEqual(summary["deadline_catchups"], 1)
        self.assertEqual(summary["closed"], 1)
        self.assertEqual(closed[0][1], "TIME_EXIT")
        self.assertEqual(closed[0][2]["trigger_type"], "TIME_EXIT")

    def test_monitor_fails_visibly_when_overdue_exit_price_is_unavailable(self):
        trade = self._staged_trade(
            opened_at=datetime.utcnow() - timedelta(hours=49),
            entry_timeframe="1h",
            exit_monitor_timeframe="5m",
            last_exit_evaluated_at=datetime.utcnow(),
        )
        fake_db = SimpleNamespace(close=Mock())

        class FakeRepo:
            def get_open_trades(self, db):
                return [trade]

            def ensure_staged_exit_policy(self, db, item):
                return False

        collector = Mock()
        collector.get_current_mark_price.return_value = None
        with patch(
            "app.jobs.paper_trade_monitor_job.SessionLocal",
            return_value=fake_db,
        ), patch(
            "app.jobs.paper_trade_monitor_job.PaperTradeRepository",
            return_value=FakeRepo(),
        ), patch(
            "app.jobs.paper_trade_monitor_job.get_final_candles_after",
            return_value=[],
        ), patch(
            "app.jobs.paper_trade_monitor_job.get_latest_candle",
            return_value=None,
        ), patch(
            "app.jobs.paper_trade_monitor_job.MarkPriceCollector",
            return_value=collector,
        ):
            summary = run_paper_trade_monitor_job()

        self.assertEqual(summary["status"], "FAILED")
        self.assertEqual(summary["overdue_unresolved"], 1)
        self.assertTrue(summary["errors"])

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
                item.remaining_position_fraction = 0.25
                item.stop_loss = 99.25
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

    def test_live_mark_above_target2_closes_long_position_immediately(self):
        base = datetime.utcnow()
        trade = self._staged_trade(
            side="LONG",
            entry_price=100.0,
            stop_loss=99.25,
            target1=101.5,
            target2=102.3,
            opened_at=base,
            entry_timeframe="1h",
            exit_monitor_timeframe="5m",
            last_exit_evaluated_at=base,
        )
        fake_db = SimpleNamespace(close=Mock())
        closes = []

        class FakeRepo:
            def get_open_trades(self, db):
                return [trade]

            def ensure_staged_exit_policy(self, db, item):
                return False

            def apply_target1(self, db, item, exit_price, **kwargs):
                item.target1_hit_at = kwargs["candle_time"]
                item.target1_exit_price = exit_price
                item.remaining_position_fraction = 0.25
                item.stop_loss = 100.75
                return item

            def close_trade(self, db, item, exit_price, result, **kwargs):
                closes.append((exit_price, result, kwargs["fill_profile"]))
                return SimpleNamespace(id=item.id, result="WIN", pnl_percent=2.0)

        collector = Mock()
        collector.get_current_mark_price.return_value = {
            "mark_price": 102.5,
            "observed_at": base + timedelta(minutes=1),
            "source": "BINANCE_FUTURES_MARK_PRICE",
        }
        with patch(
            "app.jobs.paper_trade_monitor_job.SessionLocal",
            return_value=fake_db,
        ), patch(
            "app.jobs.paper_trade_monitor_job.PaperTradeRepository",
            return_value=FakeRepo(),
        ), patch(
            "app.jobs.paper_trade_monitor_job.get_final_candles_after",
            return_value=[],
        ), patch(
            "app.jobs.paper_trade_monitor_job.get_latest_candle",
            return_value=SimpleNamespace(),
        ), patch(
            "app.jobs.paper_trade_monitor_job.MarkPriceCollector",
            return_value=collector,
        ):
            summary = run_paper_trade_monitor_job()

        self.assertEqual(summary["status"], "OK")
        self.assertEqual(summary["live_marks_evaluated"], 1)
        self.assertEqual(summary["partial_closes"], 1)
        self.assertEqual(summary["closed"], 1)
        self.assertEqual(summary["wins"], 1)
        self.assertEqual(closes[0][2]["trigger_type"], "TARGET2")

    def test_live_mark_below_target2_closes_short_remainder(self):
        trade = self._staged_trade(
            stop_loss=100.0,
            target1_hit_at=datetime(2026, 8, 10, 4, 0),
        )
        candle = SimpleNamespace(
            high_price=97.5,
            low_price=97.5,
            close_price=97.5,
            candle_time=datetime(2026, 8, 10, 5, 0),
            live_mark=True,
        )

        result = evaluate_paper_trade_exit(trade, candle)

        self.assertEqual(result["action"], "CLOSE")
        self.assertEqual(result["result"], "WIN")
        self.assertEqual(result["fill_profile"]["trigger_type"], "TARGET2")

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
