import unittest

from app.intelligence.trade_setup_engine import build_entry_trigger_decision
from app.intelligence.trade_setup_engine import build_trade_setup_decision


def tf(timeframe, signal, bias, orderflow="BUYERS_CONTROL", stale=False):
    return {
        "timeframe": timeframe,
        "signal": signal,
        "bias": bias,
        "freshness": {"is_stale": stale},
        "inputs": {
            "feature": {"is_stale": stale},
            "regime": {"is_stale": stale},
            "orderflow": {"is_stale": stale},
            "smc": {"is_stale": stale},
        },
        "component_scores": {
            "orderflow": {"value": orderflow},
        },
    }


class Phase1TradeSetupTests(unittest.TestCase):
    def test_long_only_waits_until_5m_pullback_stabilizes(self):
        result = build_trade_setup_decision(
            confirmation={
                "trade_permission": "LONG_ONLY",
                "reason": "1h is bullish while 5m is pulling back",
            },
            timeframes=[
                tf("5m", "WAIT", "WEAK_SHORT"),
                tf("15m", "WAIT", "NEUTRAL"),
                tf("1h", "LONG", "LONG"),
            ],
        )

        self.assertEqual(result["status"], "WAIT")
        self.assertEqual(result["side"], "LONG")

    def test_long_allowed_can_create_ready_setup(self):
        result = build_trade_setup_decision(
            confirmation={
                "trade_permission": "LONG_ALLOWED",
                "reason": "Higher timeframe is bullish with lower timeframe support",
            },
            timeframes=[
                tf("5m", "WAIT", "WEAK_LONG"),
                tf("15m", "WAIT", "WEAK_LONG"),
                tf("1h", "LONG", "LONG"),
            ],
        )

        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["side"], "LONG")

    def test_short_only_waits_until_5m_bounce_stabilizes(self):
        result = build_trade_setup_decision(
            confirmation={
                "trade_permission": "SHORT_ONLY",
                "reason": "1h is bearish while 5m is bouncing",
            },
            timeframes=[
                tf("5m", "WAIT", "WEAK_LONG"),
                tf("15m", "WAIT", "NEUTRAL"),
                tf("1h", "SHORT", "SHORT"),
            ],
        )

        self.assertEqual(result["status"], "WAIT")
        self.assertEqual(result["side"], "SHORT")

    def test_mixed_confirmation_waits_without_side(self):
        result = build_trade_setup_decision(
            confirmation={
                "trade_permission": "WAIT",
                "reason": "Timeframes are mixed or neutral",
            },
            timeframes=[
                tf("5m", "WAIT", "NEUTRAL"),
                tf("15m", "WAIT", "WEAK_SHORT"),
                tf("1h", "WAIT", "NEUTRAL"),
            ],
        )

        self.assertEqual(result["status"], "WAIT")
        self.assertIsNone(result["side"])

    def test_entry_trigger_waits_for_5m_bias_to_stabilize(self):
        result = build_entry_trigger_decision(
            confirmation={
                "trade_permission": "LONG_ONLY",
                "reason": "1h is bullish while 5m is pulling back",
            },
            timeframes=[
                tf("5m", "WAIT", "WEAK_SHORT"),
                tf("15m", "WAIT", "NEUTRAL"),
                tf("1h", "LONG", "LONG"),
            ],
        )

        self.assertEqual(result["status"], "WAIT")
        self.assertEqual(result["side"], "LONG")
        self.assertFalse(
            next(
                item
                for item in result["conditions"]
                if item["name"] == "lower_timeframe_bias"
            )["passed"]
        )

    def test_entry_trigger_ready_when_bias_orderflow_and_freshness_align(self):
        result = build_entry_trigger_decision(
            confirmation={
                "trade_permission": "LONG_ALLOWED",
                "reason": "Higher timeframe is bullish with lower timeframe support",
            },
            timeframes=[
                tf("5m", "WAIT", "WEAK_LONG"),
                tf("15m", "WAIT", "WEAK_LONG"),
                tf("1h", "LONG", "LONG"),
            ],
        )

        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["side"], "LONG")
        self.assertTrue(all(item["passed"] for item in result["conditions"]))

    def test_entry_trigger_requires_directional_orderflow(self):
        result = build_entry_trigger_decision(
            confirmation={
                "trade_permission": "SHORT_ALLOWED",
                "reason": "Higher timeframe is bearish with lower timeframe support",
            },
            timeframes=[
                tf("5m", "WAIT", "WEAK_SHORT", orderflow="BUYERS_CONTROL"),
                tf("15m", "WAIT", "WEAK_SHORT"),
                tf("1h", "SHORT", "SHORT"),
            ],
        )

        self.assertEqual(result["status"], "WAIT")
        self.assertFalse(
            next(
                item
                for item in result["conditions"]
                if item["name"] == "orderflow_confirmation"
            )["passed"]
        )


if __name__ == "__main__":
    unittest.main()
