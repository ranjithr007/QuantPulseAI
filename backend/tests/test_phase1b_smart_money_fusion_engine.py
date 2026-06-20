import unittest

from app.engines.smart_money_fusion_engine import SmartMoneyFusionEngine


class Obj:
    def __init__(self, **values):
        self.__dict__.update(values)


class Phase1BSmartMoneyFusionEngineTests(unittest.TestCase):
    def test_analyze_uses_database_style_fields_without_crashing(self):
        engine = SmartMoneyFusionEngine()

        result = engine.analyze(
            smc=Obj(
                bos_type="BULLISH_BOS",
                liquidity_sweep="SELL_SIDE_SWEEP",
            ),
            orderflow=Obj(
                absorption_type="BUY_ABSORPTION",
                delta=18,
                cumulative_delta=42,
                whale_buy_count=9,
                whale_sell_count=3,
            ),
        )

        self.assertEqual(result["bias"], "SMART_MONEY_LONG")
        self.assertGreater(result["score"], 50)
        self.assertIn("Sell sweep + buy absorption + CVD rising", result["reasons"])

    def test_analyze_supports_bearish_continuation_fields(self):
        engine = SmartMoneyFusionEngine()

        result = engine.analyze(
            smc=Obj(
                bos_type="BEARISH_BOS",
                liquidity_sweep="BUY_SIDE_SWEEP",
            ),
            orderflow=Obj(
                absorption_type="SELL_ABSORPTION",
                delta=-12,
                cumulative_delta=-37,
                whale_buy_count=2,
                whale_sell_count=8,
            ),
        )

        self.assertEqual(result["bias"], "SMART_MONEY_SHORT")
        self.assertLess(result["score"], 50)
        self.assertIn("Buy sweep + sell absorption + CVD falling", result["reasons"])


if __name__ == "__main__":
    unittest.main()
