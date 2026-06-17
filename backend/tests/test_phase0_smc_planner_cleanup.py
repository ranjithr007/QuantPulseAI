import unittest

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
        candles = [Candle(100, 112, 99, 108)]
        candles.extend(Candle(100, 110, 98, 105) for _ in range(9))

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


if __name__ == "__main__":
    unittest.main()
