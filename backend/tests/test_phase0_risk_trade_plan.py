import unittest

from app.risk.risk_engine import RiskEngine
from app.trading.trade_plan_engine import build_trade_plan
from app.trading.trade_plan_engine import price_precision


class Phase0RiskTradePlanTests(unittest.TestCase):
    def test_wait_trade_plan_includes_atr(self):
        trade = build_trade_plan("WAIT", 100.0)

        self.assertEqual(trade["risk_reward"], 0)
        self.assertIn("atr", trade)
        self.assertEqual(trade["atr"], 1.0)

    def test_risk_engine_rejects_wait_without_error(self):
        risk = RiskEngine().analyze("BTCUSDT", "WAIT", 100.0, 1.0, 80)

        self.assertEqual(risk["decision"], "REJECT")
        self.assertEqual(risk["reason"], "No actionable trade signal")

    def test_risk_engine_accepts_long_short_names(self):
        long_risk = RiskEngine().analyze("BTCUSDT", "LONG", 100.0, 1.0, 80)
        short_risk = RiskEngine().analyze("BTCUSDT", "SHORT", 100.0, 1.0, 80)

        self.assertEqual(long_risk["decision"], "APPROVE")
        self.assertEqual(short_risk["decision"], "APPROVE")

    def test_risk_engine_approves_valid_persisted_trade_plan(self):
        risk = RiskEngine().analyze_trade_plan(
            symbol="BTCUSDT",
            side="LONG",
            entry=100.0,
            stop_loss=99.0,
            target1=102.0,
            target2=103.0,
            confidence=80,
        )

        self.assertEqual(risk["decision"], "APPROVE")
        self.assertEqual(risk["risk_reward"], 2.0)
        self.assertGreater(risk["position_size"], 0)
        self.assertEqual(risk["risk_percent"], 1)
        self.assertNotIn("minimum_confidence", risk)

    def test_research_override_does_not_change_default_risk_confidence(self):
        default = RiskEngine().analyze_trade_plan(
            symbol="BTCUSDT",
            side="LONG",
            entry=100.0,
            stop_loss=99.0,
            target1=102.0,
            confidence=50,
        )
        research = RiskEngine().analyze_trade_plan(
            symbol="BTCUSDT",
            side="LONG",
            entry=100.0,
            stop_loss=99.0,
            target1=102.0,
            confidence=50,
            min_confidence=45,
        )

        self.assertEqual(default["decision"], "REJECT")
        self.assertEqual(default["reason"], "Confidence below risk threshold")
        self.assertEqual(research["decision"], "APPROVE")
        self.assertEqual(research["minimum_confidence"], 45)
        self.assertEqual(RiskEngine.MIN_CONFIDENCE, 65)

    def test_risk_engine_rejects_invalid_persisted_trade_plan_direction(self):
        risk = RiskEngine().analyze_trade_plan(
            symbol="BTCUSDT",
            side="LONG",
            entry=100.0,
            stop_loss=99.0,
            target1=98.0,
            confidence=20,
        )

        self.assertEqual(risk["decision"], "REJECT")
        self.assertIn("Confidence below risk threshold", risk["reason"])

    def test_trade_plan_uses_more_precision_for_low_price_symbols(self):
        trade = build_trade_plan("LONG", 1.21456, 0.00321)

        self.assertEqual(trade["price_precision"], 5)
        self.assertEqual(trade["entry"], 1.21456)
        self.assertEqual(trade["stop_loss"], 1.21135)
        self.assertEqual(trade["target1"], 1.22098)

    def test_trade_plan_keeps_two_decimals_for_large_price_symbols(self):
        trade = build_trade_plan("LONG", 65688.0, 63.2278)

        self.assertEqual(trade["price_precision"], 2)
        self.assertEqual(trade["entry"], 65688.0)
        self.assertEqual(trade["stop_loss"], 65624.77)
        self.assertEqual(trade["target1"], 65814.46)

    def test_price_precision_bands(self):
        self.assertEqual(price_precision(0.5), 6)
        self.assertEqual(price_precision(1.2), 5)
        self.assertEqual(price_precision(74.54), 4)
        self.assertEqual(price_precision(613.39), 2)


if __name__ == "__main__":
    unittest.main()
