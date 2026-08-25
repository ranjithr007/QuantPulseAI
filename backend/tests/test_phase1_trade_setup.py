import unittest

from app.intelligence.trade_setup_engine import build_entry_trigger_decision
from app.intelligence.trade_setup_engine import build_trade_setup_decision
from app.intelligence.trade_setup_engine import CONFIDENCE_WINDOWS


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


def governed_tf(timeframe, score, confidence=None, orderflow=None, stale=False):
    signal = "LONG" if score >= 40 else "SHORT" if score <= -40 else "WAIT"
    bias = "LONG" if score >= 40 else "SHORT" if score <= -40 else "NEUTRAL"
    if orderflow is None:
        orderflow = "SELLERS_CONTROL" if score < 0 else "BUYERS_CONTROL"
    item = tf(timeframe, signal, bias, orderflow=orderflow, stale=stale)
    item["score"] = score
    item["confidence"] = abs(score) if confidence is None else confidence
    return item


class Phase1TradeSetupTests(unittest.TestCase):
    def test_governed_timeframes_share_40_minimum_and_60_full_size_boundary(self):
        for timeframe in ("1h", "2h", "4h", "1d"):
            self.assertEqual(
                CONFIDENCE_WINDOWS[timeframe],
                {"min": 40.0, "preferred": 60.0, "max": 100.0},
            )

    def test_governed_short_at_49_is_ready_without_timeframe_penalty(self):
        result = build_entry_trigger_decision(
            confirmation={
                "trade_permission": "SHORT_ALLOWED",
                "reason": "Bearish candidate is allowed",
                "entry_timeframes": [],
            },
            timeframes=[
                governed_tf("1h", -49),
                governed_tf("2h", 0, confidence=100),
                governed_tf("4h", 0, confidence=100),
                governed_tf("1d", 0, confidence=100),
            ],
        )

        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["side"], "SHORT")
        self.assertEqual(result["entry_timeframe"], "1h")
        self.assertEqual(result["confidence_window"]["min"], 40.0)
        self.assertTrue(all(item["passed"] for item in result["conditions"]))

    def test_governed_candidate_can_execute_when_aggregate_stack_is_mixed(self):
        result = build_entry_trigger_decision(
            confirmation={
                "trade_permission": "WAIT",
                "reason": "Timeframes are mixed or neutral",
                "entry_timeframes": [],
            },
            timeframes=[
                governed_tf("1h", -49),
                governed_tf("2h", 0),
                governed_tf("4h", 0),
                governed_tf("1d", 0),
            ],
        )

        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["side"], "SHORT")
        self.assertEqual(result["entry_timeframe"], "1h")

    def test_governed_entry_selects_strongest_valid_timeframe(self):
        result = build_entry_trigger_decision(
            confirmation={
                "trade_permission": "LONG_ALLOWED",
                "reason": "Bullish candidates are allowed",
                "entry_timeframes": [],
            },
            timeframes=[
                governed_tf("1h", 45),
                governed_tf("2h", 55),
                governed_tf("4h", 70),
                governed_tf("1d", 65),
            ],
        )

        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["side"], "LONG")
        self.assertEqual(result["entry_timeframe"], "4h")
        self.assertEqual(len(result["timeframe_candidates"]), 4)

    def test_governed_entry_blocks_directional_score_when_core_input_is_stale(self):
        stale_orderflow = governed_tf("1h", 53.4)
        stale_orderflow["contradiction"] = {
            "status": "INVALIDATED",
            "trade_allowed": False,
            "summary": "One or more core inputs are stale or missing",
            "reasons": ["Orderflow input is stale"],
        }
        result = build_entry_trigger_decision(
            confirmation={
                "trade_permission": "LONG_ALLOWED",
                "reason": "Bullish candidates are allowed",
                "entry_timeframes": [],
            },
            timeframes=[
                stale_orderflow,
                governed_tf("2h", 0),
                governed_tf("4h", 0),
                governed_tf("1d", 0),
            ],
        )

        self.assertEqual(result["status"], "WAIT")
        self.assertEqual(result["side"], "LONG")
        self.assertEqual(result["reason"], "Orderflow input is stale")
        core_gate = next(
            item
            for item in result["conditions"]
            if item["name"] == "core_input_confirmation"
        )
        self.assertFalse(core_gate["passed"])

    def test_governed_score_below_40_waits_even_when_signal_label_is_directional(self):
        weak = governed_tf("1h", 39.99)
        weak["signal"] = "LONG"
        result = build_entry_trigger_decision(
            confirmation={
                "trade_permission": "LONG_ALLOWED",
                "reason": "Longs are allowed",
                "entry_timeframes": [],
            },
            timeframes=[
                weak,
                governed_tf("2h", 0),
                governed_tf("4h", 0),
                governed_tf("1d", 0),
            ],
        )

        self.assertEqual(result["status"], "WAIT")
        self.assertIsNone(result["side"])

    def test_governed_confidence_below_40_is_not_rescued_by_stack_confidence(self):
        result = build_entry_trigger_decision(
            confirmation={
                "trade_permission": "SHORT_ALLOWED",
                "reason": "Shorts are allowed",
                "entry_timeframes": [],
            },
            timeframes=[
                governed_tf("1h", -49, confidence=39.99),
                governed_tf("2h", 0, confidence=100),
                governed_tf("4h", 0, confidence=100),
                governed_tf("1d", 0, confidence=100),
            ],
        )

        self.assertEqual(result["status"], "WAIT")
        self.assertEqual(result["side"], "SHORT")
        confidence_gate = next(
            item for item in result["conditions"] if item["name"] == "confidence_window"
        )
        self.assertFalse(confidence_gate["passed"])

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
