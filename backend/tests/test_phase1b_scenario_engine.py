import unittest

from app.intelligence.scenario_engine import build_scenario_plan


def tf(timeframe, signal, bias, stale=False, price=100):
    return {
        "timeframe": timeframe,
        "signal": signal,
        "bias": bias,
        "current_price": price,
        "freshness": {"is_stale": stale},
    }


class Phase1BScenarioEngineTests(unittest.TestCase):
    def test_bullish_pullback_prioritizes_long_continuation(self):
        scenario = build_scenario_plan(
            confirmation={
                "overall_bias": "BULLISH_PULLBACK",
                "trade_permission": "LONG_ONLY",
                "reason": "1h bullish while 5m is pulling back",
            },
            timeframes=[
                tf("5m", "WAIT", "WEAK_SHORT"),
                tf("15m", "WAIT", "WEAK_LONG"),
                tf("1h", "LONG", "LONG"),
            ],
            current_price=100,
            atr=10,
        )

        self.assertEqual(scenario["scenario_type"], "BULLISH_CONTINUATION")
        self.assertEqual(scenario["primary_path"]["direction"], "LONG")
        self.assertEqual(sum(path["probability"] for path in scenario["paths"]), 100)

    def test_mixed_context_prioritizes_range_rotation(self):
        scenario = build_scenario_plan(
            confirmation={
                "overall_bias": "MIXED",
                "trade_permission": "WAIT",
                "reason": "Timeframes are mixed or neutral",
            },
            timeframes=[
                tf("5m", "WAIT", "WEAK_SHORT"),
                tf("15m", "WAIT", "WEAK_SHORT"),
                tf("1h", "WAIT", "NEUTRAL"),
            ],
            current_price=100,
            atr=10,
        )

        self.assertEqual(scenario["scenario_type"], "RANGE_ROTATION")
        self.assertGreaterEqual(scenario["primary_path"]["probability"], 35)

    def test_stale_or_no_data_lifts_invalidation_probability(self):
        scenario = build_scenario_plan(
            confirmation={
                "overall_bias": "NO_DATA",
                "trade_permission": "BLOCKED",
                "reason": "One or more required timeframes have no signal data",
            },
            timeframes=[
                tf("5m", "NO_DATA", "NO_DATA", stale=True),
                tf("15m", "WAIT", "NEUTRAL", stale=True),
                tf("1h", "WAIT", "NEUTRAL", stale=True),
            ],
            current_price=100,
            atr=10,
        )

        invalidation = next(
            path for path in scenario["paths"] if path["name"] == "INVALIDATION"
        )

        self.assertEqual(scenario["scenario_type"], "INVALIDATION")
        self.assertGreaterEqual(invalidation["probability"], 40)


if __name__ == "__main__":
    unittest.main()
