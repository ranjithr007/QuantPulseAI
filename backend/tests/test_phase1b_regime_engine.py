import json
import unittest

from app.intelligence.master_ai_engine import score_master_signal_components
from app.regimes.regime_engine import analyze_market
from app.regimes.regime_engine import build_regime_contract
from app.regimes.regime_engine import direction_aware_transition_research
from app.regimes.regime_engine import parse_regime_audit
from app.regimes.regime_engine import regime_catalog
from app.regimes.rules import REGIME_DEFINITIONS
from app.regimes.rules import detect_regime
from app.regimes.rules import detect_regime_momentum_boundary_research


class Obj:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def feature(
    trend=50,
    momentum=50,
    volatility=50,
    liquidity=50,
    final_score=50,
):
    return Obj(
        Symbol="BTCUSDT",
        Timeframe="5m",
        TrendScore=trend,
        MomentumScore=momentum,
        VolatilityScore=volatility,
        LiquidityScore=liquidity,
        FinalScore=final_score,
        Trend="BULLISH" if trend > 60 else "BEARISH" if trend < 40 else "RANGE",
        Signal="BUY" if final_score > 70 else "SELL" if final_score < 40 else "WAIT",
    )


class Phase1BRegimeEngineTests(unittest.TestCase):
    def test_regime_catalog_contains_13_v3_regimes(self):
        catalog = regime_catalog()
        contract = build_regime_contract()

        self.assertEqual(len(REGIME_DEFINITIONS), 13)
        self.assertEqual(catalog["count"], 13)
        self.assertIn("TRENDING_BULL", REGIME_DEFINITIONS)
        self.assertIn("TRENDING_BEAR", REGIME_DEFINITIONS)
        self.assertIn("MANIPULATION_PHASE", REGIME_DEFINITIONS)
        self.assertIn("LOW_VOLATILITY_COMPRESSION", REGIME_DEFINITIONS)
        self.assertEqual(contract["version"], "v3_regime_13_v1")
        self.assertEqual(contract["thresholds"]["min_transition_confidence"], 62)
        self.assertEqual(contract["thresholds"]["hysteresis_margin"], 7)
        self.assertEqual(contract["count"], 13)
        self.assertEqual(len(contract["taxonomy"]), 13)

    def test_detects_representative_v3_regimes(self):
        cases = [
            (feature(trend=82, momentum=74), "TRENDING_BULL"),
            (feature(trend=18, momentum=24), "TRENDING_BEAR"),
            (feature(trend=66, momentum=42), "BULL_PULLBACK"),
            (feature(trend=34, momentum=58), "BEAR_RALLY"),
            (feature(trend=50, momentum=50, volatility=18), "LOW_VOLATILITY_COMPRESSION"),
            (
                feature(trend=52, momentum=60, volatility=90, liquidity=92),
                "LIQUIDITY_GRAB_BULLISH",
            ),
            (
                feature(trend=48, momentum=40, volatility=90, liquidity=92),
                "LIQUIDITY_GRAB_BEARISH",
            ),
            (
                feature(trend=50, momentum=50, volatility=90, liquidity=92),
                "MANIPULATION_PHASE",
            ),
        ]

        for item, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(detect_regime(item)["regime"], expected)

        self.assertEqual(detect_regime(feature(trend=82, momentum=74))["direction"], "BULLISH")
        self.assertEqual(detect_regime(feature(trend=18, momentum=24))["direction"], "BEARISH")
        self.assertEqual(
            detect_regime(feature(trend=50, momentum=50, volatility=18))["direction"],
            "NEUTRAL",
        )

    def test_research_momentum_boundaries_do_not_change_production_detector(self):
        bullish_boundary = feature(trend=82, momentum=60)
        bearish_boundary = feature(trend=18, momentum=40)

        self.assertNotEqual(detect_regime(bullish_boundary)["regime"], "TRENDING_BULL")
        self.assertNotEqual(detect_regime(bearish_boundary)["regime"], "TRENDING_BEAR")
        self.assertEqual(
            detect_regime_momentum_boundary_research(bullish_boundary)["regime"],
            "TRENDING_BULL",
        )
        self.assertEqual(
            detect_regime_momentum_boundary_research(bearish_boundary)["regime"],
            "TRENDING_BEAR",
        )
        self.assertEqual(
            analyze_market(
                bullish_boundary,
                None,
                regime_detector=detect_regime_momentum_boundary_research,
            )["regime"],
            "TRENDING_BULL",
        )

    def test_hysteresis_holds_previous_regime_and_increments_dwell(self):
        previous = Obj(
            Regime="TRENDING_BULL",
            Confidence=80,
            Reason=json.dumps({"dwell_cycles": 2}),
        )

        result = analyze_market(feature(trend=39, momentum=51), previous)

        self.assertEqual(result["regime"], "TRENDING_BULL")
        self.assertEqual(result["transition_decision"], "HELD_PREVIOUS")
        self.assertEqual(result["dwell_cycles"], 3)
        self.assertEqual(parse_regime_audit(result["reason"])["dwell_cycles"], 3)

    def test_confirmed_transition_resets_dwell(self):
        previous = Obj(
            Regime="TRENDING_BULL",
            Confidence=70,
            Reason=json.dumps({"dwell_cycles": 4}),
        )

        result = analyze_market(feature(trend=12, momentum=18), previous)

        self.assertEqual(result["regime"], "TRENDING_BEAR")
        self.assertEqual(result["transition_decision"], "CONFIRMED_TRANSITION")
        self.assertEqual(result["dwell_cycles"], 1)

    def test_direction_aware_research_policy_does_not_change_production_hysteresis(self):
        previous = Obj(
            Regime="TRENDING_BULL",
            Confidence=80,
            Reason=json.dumps({"dwell_cycles": 5}),
        )
        bearish_boundary = feature(trend=18, momentum=40)

        production = analyze_market(
            bearish_boundary,
            previous,
            regime_detector=detect_regime_momentum_boundary_research,
        )
        research = analyze_market(
            bearish_boundary,
            previous,
            regime_detector=detect_regime_momentum_boundary_research,
            transition_policy=direction_aware_transition_research,
        )

        self.assertEqual(production["regime"], "TRENDING_BULL")
        self.assertEqual(production["transition_decision"], "HELD_PREVIOUS")
        self.assertEqual(research["regime"], "TRENDING_BEAR")
        self.assertEqual(
            research["transition_decision"],
            "CONFIRMED_DIRECTION_REVERSAL_RESEARCH",
        )
        self.assertEqual(research["dwell_cycles"], 1)

    def test_regime_audit_reason_is_json_serialized(self):
        result = analyze_market(feature(trend=82, momentum=74), None)

        audit = parse_regime_audit(result["reason"])
        self.assertEqual(audit["engine_version"], "v3_regime_13_v1")
        self.assertEqual(audit["selected_regime"], "TRENDING_BULL")

    def test_master_signal_scores_expanded_bull_and_bear_regime_names(self):
        bullish = score_master_signal_components(
            None,
            Obj(Regime="BULL_PULLBACK"),
            None,
            None,
        )
        bearish = score_master_signal_components(
            None,
            Obj(Regime="BEAR_RALLY"),
            None,
            None,
        )

        self.assertEqual(bullish["regime"]["score"], 15)
        self.assertEqual(bearish["regime"]["score"], -15)


if __name__ == "__main__":
    unittest.main()
