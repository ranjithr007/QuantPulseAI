import unittest

from app.features.feature_quality_engine import build_feature_quality_profile


class Candle:
    def __init__(self, close_price, high_price=None, low_price=None, volume=100, candle_time=None):
        self.close_price = close_price
        self.high_price = high_price if high_price is not None else close_price * 1.01
        self.low_price = low_price if low_price is not None else close_price * 0.99
        self.volume = volume
        self.candle_time = candle_time


class FeatureQualityEngineTests(unittest.TestCase):
    def test_quality_profile_uses_sentiment_and_correlation(self):
        candles = [
            Candle(100),
            Candle(102),
            Candle(104),
            Candle(106),
            Candle(108),
            Candle(110),
        ]
        benchmark = [
            Candle(50),
            Candle(51),
            Candle(52),
            Candle(53),
            Candle(54),
            Candle(55),
        ]
        profile = build_feature_quality_profile(
            db=None,
            symbol="ETHUSDT",
            timeframe="5m",
            feature={
                "TrendScore": 82,
                "MomentumScore": 76,
                "VolatilityScore": 48,
                "LiquidityScore": 72,
                "FinalScore": 74,
                "Trend": "BULLISH",
                "ATR": 3.5,
            },
            candles=candles,
            benchmark_candles=benchmark,
            benchmark_symbol="BTCUSDT",
            window=6,
        )

        self.assertEqual(profile["status"], "OK")
        self.assertEqual(profile["sentiment"]["sentiment"], "BULLISH")
        self.assertEqual(profile["correlation"]["signal"], "ALIGNED")
        self.assertGreater(profile["quality_score"], 60)
        self.assertIn("Trend is bullish", profile["quality_notes"])

    def test_quality_profile_handles_missing_candles(self):
        profile = build_feature_quality_profile(
            db=None,
            symbol="SOLUSDT",
            timeframe="5m",
            feature=None,
            candles=[],
            benchmark_candles=[],
            benchmark_symbol="BTCUSDT",
            window=6,
        )

        self.assertEqual(profile["status"], "NO_DATA")
        self.assertEqual(profile["quality_score"], 0)
        self.assertEqual(profile["sentiment"]["sentiment"], "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
