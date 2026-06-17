import unittest

from app.intelligence.multi_timeframe_engine import combine_timeframe_signals


def tf(timeframe, signal, bias):
    return {"timeframe": timeframe, "signal": signal, "bias": bias}


class Phase1MultiTimeframeTests(unittest.TestCase):
    def test_bullish_pullback_when_1h_bullish_and_5m_weak_short(self):
        result = combine_timeframe_signals(
            [
                tf("5m", "WAIT", "WEAK_SHORT"),
                tf("15m", "WAIT", "NEUTRAL"),
                tf("1h", "LONG", "LONG"),
            ]
        )

        self.assertEqual(result["overall_bias"], "BULLISH_PULLBACK")
        self.assertEqual(result["trade_permission"], "LONG_ONLY")

    def test_bearish_pullback_when_1h_bearish_and_5m_weak_long(self):
        result = combine_timeframe_signals(
            [
                tf("5m", "WAIT", "WEAK_LONG"),
                tf("15m", "WAIT", "NEUTRAL"),
                tf("1h", "SHORT", "SHORT"),
            ]
        )

        self.assertEqual(result["overall_bias"], "BEARISH_PULLBACK")
        self.assertEqual(result["trade_permission"], "SHORT_ONLY")

    def test_alignment_allows_directional_trade(self):
        result = combine_timeframe_signals(
            [
                tf("5m", "WAIT", "WEAK_LONG"),
                tf("15m", "WAIT", "WEAK_LONG"),
                tf("1h", "LONG", "LONG"),
            ]
        )

        self.assertEqual(result["overall_bias"], "BULLISH_ALIGNMENT")
        self.assertEqual(result["trade_permission"], "LONG_ALLOWED")

    def test_no_data_blocks_trade_permission(self):
        result = combine_timeframe_signals(
            [
                tf("5m", "WAIT", "NEUTRAL"),
                tf("15m", "NO_DATA", "NO_DATA"),
                tf("1h", "LONG", "LONG"),
            ]
        )

        self.assertEqual(result["overall_bias"], "NO_DATA")
        self.assertEqual(result["trade_permission"], "BLOCKED")

    def test_custom_timeframe_labels_are_used_in_reason(self):
        result = combine_timeframe_signals(
            [
                tf("15m", "WAIT", "WEAK_SHORT"),
                tf("1h", "WAIT", "NEUTRAL"),
                tf("4h", "LONG", "LONG"),
            ]
        )

        self.assertEqual(result["overall_bias"], "BULLISH_PULLBACK")
        self.assertEqual(result["trade_permission"], "LONG_ONLY")
        self.assertEqual(result["reason"], "4h is bullish while 15m is pulling back")


if __name__ == "__main__":
    unittest.main()
