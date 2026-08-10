import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta
from app.jobs import smc_job
from app.smc.liquidity_sweep_engine import LiquiditySweepEngine
from app.smc.order_block_engine import OrderBlockEngine
from app.trading.planner.invalidation_engine import InvalidationEngine
from app.trading.planner.trade_planner import TradePlanner


class Candle:
    def __init__(self, open_price, high_price, low_price, close_price):
        self.open_price = open_price
        self.high_price = high_price
        self.low_price = low_price
        self.close_price = close_price


class Phase0SmcPlannerCleanupTests(unittest.TestCase):
    def test_liquidity_sweep_engine_normalizes_detector_result(self):
        candles = [Candle(100, 110, 98, 105) for _ in range(9)]
        candles.append(Candle(100, 112, 99, 108))

        result = LiquiditySweepEngine().analyze(candles)

        self.assertTrue(result["detected"])
        self.assertEqual(result["direction"], "BUY_SIDE_SWEEP")
        self.assertEqual(result["price"], 112)

    def test_order_block_engine_normalizes_detector_result(self):
        candles = [Candle(100, 112, 99, 111)]

        result = OrderBlockEngine().analyze(candles)

        self.assertEqual(result["type"], "BULLISH")
        self.assertEqual(result["price"], 99)
        self.assertGreater(result["confidence"], 0)

    def test_invalidation_engine_generates_side_specific_rules(self):
        long_result = InvalidationEngine().calculate("LONG", 100, 95, 2)
        short_result = InvalidationEngine().calculate("SHORT", 100, 105, 2)

        self.assertLess(long_result["price"], 95)
        self.assertGreater(short_result["price"], 105)

    def test_trade_planner_includes_invalidation(self):
        plan = TradePlanner().create_plan(
            {"symbol": "BTCUSDT", "decision": "LONG", "confidence": 80},
            price=100,
            atr=2,
        )

        self.assertEqual(plan["side"], "LONG")
        self.assertIn("invalidation", plan)
        self.assertIn("price", plan["invalidation"])

    def test_run_smc_job_uses_engine_and_skips_legacy_path(self):
        candles = [
            Candle(
                open_price=100,
                high_price=112,
                low_price=99,
                close_price=108,
            )
            for index in range(20)
        ]

        db = MagicMock()

        # Make the SQLAlchemy query mock independent of the exact number
        # of filter/order_by/limit calls.
        query = MagicMock()
        query.filter.return_value = query
        query.order_by.return_value = query
        query.limit.return_value = query
        query.all.return_value = candles

        db.query.return_value = query

        active_symbols = [SimpleNamespace(symbol="DOGEUSDT")]

        smc_repo = MagicMock()

        engine_result = {
            "structure": "RANGE",
            "reason": [],
        }

        with patch.object(
            smc_job,
            "SessionLocal",
            return_value=db,
        ), patch.object(
            smc_job.SymbolRepository,
            "get_active_symbols",
            return_value=active_symbols,
        ) as symbols_mock, patch.object(
            smc_job,
            "smc_repo",
            smc_repo,
        ), patch.object(
            smc_job.engine,
            "analyze",
            return_value=engine_result,
        ) as analyze_mock, patch.object(
            smc_job,
            "run_smc_analysis",
            create=True,
            side_effect=AssertionError("legacy SMC path should not be called"),
        ) as legacy_mock:
            smc_job.run_smc_job()

        symbols_mock.assert_called_once_with(db)

        self.assertEqual(analyze_mock.call_count,len(smc_job.TIMEFRAMES))

        legacy_mock.assert_not_called()
        db.close.assert_called_once()

    def test_find_swings_detects_a_single_confirmed_swing_bar(self):
        candles = [
            Candle(10, 11, 9, 10),
            Candle(10, 12, 8, 11),
            Candle(11, 15, 6, 12),
            Candle(12, 12, 8, 11),
            Candle(11, 11, 9, 10),
        ]

        swing_highs, swing_lows = smc_job.engine.find_swings(candles)

        self.assertEqual(len(swing_highs), 1)
        self.assertEqual(swing_highs[0].index, 2)
        self.assertEqual(swing_highs[0].high_price, 15.0)
        self.assertEqual(len(swing_lows), 1)
        self.assertEqual(swing_lows[0].index, 2)
        self.assertEqual(swing_lows[0].low_price, 6.0)


if __name__ == "__main__":
    unittest.main()
