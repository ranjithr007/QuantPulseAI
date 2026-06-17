import unittest

from app.intelligence.master_ai_engine import generate_master_signal
from app.intelligence.master_ai_engine import score_master_signal_components


class Obj:
    def __init__(self, **values):
        self.__dict__.update(values)


class Phase0MasterSignalTests(unittest.TestCase):
    def test_uses_database_style_uppercase_fields(self):
        result = generate_master_signal(
            feature=Obj(Trend="BULLISH"),
            regime=Obj(Regime="TRENDING_BULL"),
            orderflow=Obj(FlowSignal="BUYERS_CONTROL"),
            smc=Obj(smc_bias="LONG"),
        )

        self.assertEqual(result["signal"], "LONG")
        self.assertEqual(result["bias"], "LONG")
        self.assertEqual(result["score"], 100)
        self.assertEqual(result["confidence"], 100)

    def test_wait_can_show_weak_short_bias(self):
        result = generate_master_signal(
            feature=Obj(Trend="BEARISH"),
            regime=None,
            orderflow=None,
            smc=None,
        )

        self.assertEqual(result["signal"], "WAIT")
        self.assertEqual(result["bias"], "WEAK_SHORT")
        self.assertEqual(result["score"], -20)

    def test_wait_can_show_weak_long_bias(self):
        result = generate_master_signal(
            feature=None,
            regime=None,
            orderflow=Obj(FlowSignal="BUYERS_CONTROL"),
            smc=None,
        )

        self.assertEqual(result["signal"], "WAIT")
        self.assertEqual(result["bias"], "WEAK_LONG")
        self.assertEqual(result["score"], 25)

    def test_low_score_wait_is_neutral_bias(self):
        result = generate_master_signal(
            feature=Obj(Trend="BEARISH"),
            regime=None,
            orderflow=Obj(FlowSignal="BUYERS_CONTROL"),
            smc=None,
        )

        self.assertEqual(result["signal"], "WAIT")
        self.assertEqual(result["bias"], "NEUTRAL")
        self.assertEqual(result["score"], 5)

    def test_component_scores_explain_total_score(self):
        components = score_master_signal_components(
            feature=Obj(Trend="BEARISH"),
            regime=Obj(Regime="TRENDING_BEAR"),
            orderflow=Obj(FlowSignal="BUYERS_CONTROL"),
            smc=None,
        )

        self.assertEqual(components["feature"]["score"], -20)
        self.assertEqual(components["regime"]["score"], -25)
        self.assertEqual(components["orderflow"]["score"], 25)
        self.assertEqual(components["smc"]["score"], 0)
        self.assertEqual(
            sum(component["score"] for component in components.values()),
            -20,
        )


if __name__ == "__main__":
    unittest.main()
