import unittest

from app.intelligence.probability_engine import ProbabilityEngine


class Phase1BProbabilityEngineTests(unittest.TestCase):
    def test_fresh_long_setup_favors_long_probability(self):
        engine = ProbabilityEngine()
        report = engine.analyze(
            symbol="BTCUSDT",
            timeframe="5m",
            signal={
                "signal": "LONG",
                "bias": "LONG",
                "score": 62,
                "confidence": 62,
                "reasons": ["Feature trend bullish", "Bull regime"],
            },
            components={
                "feature": {"score": 20},
                "regime": {"score": 25},
                "orderflow": {"score": 25},
                "smc": {"score": 30},
            },
            contradiction={"status": "CLEAR", "conflict_score": 0},
            freshness={
                "candle": {"is_stale": False, "data_age_seconds": 0},
                "feature": {"is_stale": False, "data_age_seconds": 60},
                "regime": {"is_stale": False, "data_age_seconds": 60},
                "orderflow": {"is_stale": False, "data_age_seconds": 60},
                "smc": {"is_stale": False, "data_age_seconds": 60},
            },
            current_price=100,
            previous_price=98,
            price_change_pct=2.04,
        )

        self.assertEqual(report["decision"], "LONG")
        self.assertGreater(report["probabilities"]["LONG"], report["probabilities"]["SHORT"])
        self.assertAlmostEqual(sum(report["probabilities"].values()), 100, places=2)
        self.assertGreater(report["confidence"], 50)

    def test_invalidated_inputs_force_wait_and_high_risk_status(self):
        engine = ProbabilityEngine()
        report = engine.analyze(
            symbol="SOLUSDT",
            timeframe="5m",
            signal={
                "signal": "WAIT",
                "bias": "NEUTRAL",
                "score": 0,
                "confidence": 5,
                "reasons": [],
            },
            components={
                "feature": {"score": -20},
                "regime": {"score": -25},
                "orderflow": {"score": 0},
                "smc": {"score": 0},
            },
            contradiction={"status": "INVALIDATED", "conflict_score": 100},
            freshness={
                "candle": {"is_stale": True, "data_age_seconds": 5000},
                "feature": {"is_stale": True, "data_age_seconds": 5000},
                "regime": {"is_stale": True, "data_age_seconds": 5000},
                "orderflow": {"is_stale": True, "data_age_seconds": 5000},
                "smc": {"is_stale": True, "data_age_seconds": 5000},
            },
        )

        self.assertEqual(report["status"], "INVALIDATED")
        self.assertEqual(report["decision"], "WAIT")
        self.assertFalse(report["actionable"])
        self.assertGreater(report["probabilities"]["WAIT"], 80)


if __name__ == "__main__":
    unittest.main()
