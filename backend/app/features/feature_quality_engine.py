from math import sqrt

from app.engines.sentiment_engine import SentimentEngine
from app.repositories.candle_repository import get_latest_candles


class FeatureQualityEngine:
    def __init__(self):
        self.sentiment_engine = SentimentEngine()

    def build(
        self,
        db,
        symbol,
        timeframe,
        feature=None,
        candles=None,
        benchmark_candles=None,
        benchmark_symbol=None,
        window=30,
    ):
        if candles is None:
            if db is None:
                candles = []
            else:
                candles = get_latest_candles(db, symbol, timeframe, limit=max(window, 60))
        candles = _ordered_candles(candles)
        benchmark_symbol = benchmark_symbol or _benchmark_symbol(symbol)
        if benchmark_candles is None and db is not None:
            benchmark_candles = _ordered_candles(
                get_latest_candles(db, benchmark_symbol, timeframe, limit=max(window, 60))
            )
        benchmark_candles = _ordered_candles(benchmark_candles or [])

        base = {
            "symbol": symbol,
            "timeframe": timeframe,
            "benchmark_symbol": benchmark_symbol,
            "sample_size": len(candles),
            "benchmark_sample_size": len(benchmark_candles),
        }

        if not candles:
            return {
                **base,
                "status": "NO_DATA",
                "sentiment": {"sentiment": "UNKNOWN", "sentiment_score": 50, "reason": "No candle data"},
                "sentiment_score": 50,
                "correlation": {
                    "benchmark_symbol": benchmark_symbol,
                    "correlation": 0,
                    "correlation_score": 50,
                    "signal": "NEUTRAL",
                    "reason": "No candle data",
                },
                "correlation_score": 50,
                "quality_score": 0,
                "quality_bias": "UNAVAILABLE",
                "quality_notes": ["No candle data"],
            }

        trend_score = _feature_value(feature, "TrendScore", 50)
        momentum_score = _feature_value(feature, "MomentumScore", 50)
        volatility_score = _feature_value(feature, "VolatilityScore", 50)
        liquidity_score = _feature_value(feature, "LiquidityScore", 50)
        final_score = _feature_value(feature, "FinalScore", 50)
        trend = _feature_value(feature, "Trend", "UNKNOWN")

        sentiment = self.sentiment_engine.analyze(
            fear_greed_score=trend_score,
            news_score=momentum_score,
            social_score=liquidity_score,
        )
        correlation = self._correlation_profile(candles, benchmark_candles, benchmark_symbol)
        stability_score = self._stability_score(volatility_score)
        completeness_score = self._completeness_score(feature)
        quality_score = round(
            final_score * 0.35
            + sentiment["sentiment_score"] * 0.2
            + correlation["correlation_score"] * 0.2
            + stability_score * 0.15
            + completeness_score * 0.1,
            2,
        )

        if quality_score >= 70:
            quality_bias = "STRONG"
        elif quality_score >= 55:
            quality_bias = "BALANCED"
        elif quality_score >= 40:
            quality_bias = "WATCH"
        else:
            quality_bias = "WEAK"

        quality_notes = []
        if sentiment["sentiment"] != "NEUTRAL":
            quality_notes.append(f"Sentiment leaning {sentiment['sentiment'].lower()}")
        if correlation["signal"] != "NEUTRAL":
            quality_notes.append(f"Correlation is {correlation['signal'].lower()}")
        if volatility_score >= 70:
            quality_notes.append("Volatility elevated")
        if trend in {"BULLISH", "BEARISH"}:
            quality_notes.append(f"Trend is {trend.lower()}")

        return {
            **base,
            "status": "OK",
            "trend_score": trend_score,
            "momentum_score": momentum_score,
            "volatility_score": volatility_score,
            "liquidity_score": liquidity_score,
            "final_score": final_score,
            "trend": trend,
            "sentiment": sentiment,
            "sentiment_score": sentiment["sentiment_score"],
            "correlation": correlation,
            "correlation_score": correlation["correlation_score"],
            "stability_score": stability_score,
            "completeness_score": completeness_score,
            "quality_score": quality_score,
            "quality_bias": quality_bias,
            "quality_notes": quality_notes,
        }

    def _correlation_profile(self, candles, benchmark_candles, benchmark_symbol):
        symbol_returns = _returns(candles)
        benchmark_returns = _returns(benchmark_candles)
        paired = list(zip(symbol_returns, benchmark_returns))

        if len(paired) < 5:
            return {
                "benchmark_symbol": benchmark_symbol,
                "correlation": 0,
                "correlation_score": 50,
                "signal": "NEUTRAL",
                "reason": "Insufficient paired candles",
            }

        correlation = _pearson([item[0] for item in paired], [item[1] for item in paired])
        correlation_score = round((correlation + 1) * 50, 2)

        if correlation >= 0.6:
            signal = "ALIGNED"
            reason = "Price action is aligned with the benchmark"
        elif correlation <= -0.6:
            signal = "INVERSE"
            reason = "Price action is inversely related to the benchmark"
        else:
            signal = "NEUTRAL"
            reason = "Price action is only loosely correlated with the benchmark"

        return {
            "benchmark_symbol": benchmark_symbol,
            "correlation": round(correlation, 4),
            "correlation_score": correlation_score,
            "signal": signal,
            "reason": reason,
        }

    @staticmethod
    def _stability_score(volatility_score):
        score = 100 - abs(float(volatility_score) - 50) * 2
        return round(max(0, min(100, score)), 2)

    @staticmethod
    def _completeness_score(feature):
        if feature is None:
            return 0

        values = [
            _feature_value(feature, "TrendScore", None),
            _feature_value(feature, "MomentumScore", None),
            _feature_value(feature, "VolatilityScore", None),
            _feature_value(feature, "LiquidityScore", None),
            _feature_value(feature, "FinalScore", None),
            _feature_value(feature, "ATR", None),
        ]
        available = sum(1 for value in values if value is not None)
        return round((available / len(values)) * 100, 2)


def build_feature_quality_profile(
    db,
    symbol,
    timeframe,
    feature=None,
    candles=None,
    benchmark_candles=None,
    benchmark_symbol=None,
    window=30,
):
    return FeatureQualityEngine().build(
        db=db,
        symbol=symbol,
        timeframe=timeframe,
        feature=feature,
        candles=candles,
        benchmark_candles=benchmark_candles,
        benchmark_symbol=benchmark_symbol,
        window=window,
    )


def _ordered_candles(candles):
    if not candles:
        return []

    return sorted(
        candles,
        key=lambda item: (
            getattr(item, "candle_time", None) is None,
            getattr(item, "candle_time", None) or 0,
        ),
    )


def _benchmark_symbol(symbol):
    symbol = (symbol or "").upper()
    if symbol == "BTCUSDT":
        return "ETHUSDT"
    return "BTCUSDT"


def _returns(candles):
    ordered = _ordered_candles(candles)
    if len(ordered) < 2:
        return []

    returns = []
    for index in range(1, len(ordered)):
        previous = float(ordered[index - 1].close_price)
        current = float(ordered[index].close_price)
        if previous == 0:
            continue
        returns.append((current - previous) / abs(previous))
    return returns


def _pearson(xs, ys):
    if len(xs) != len(ys) or len(xs) < 2:
        return 0.0

    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    denominator_x = sqrt(sum((x - mean_x) ** 2 for x in xs))
    denominator_y = sqrt(sum((y - mean_y) ** 2 for y in ys))

    if denominator_x == 0 or denominator_y == 0:
        return 0.0

    return max(-1.0, min(1.0, numerator / (denominator_x * denominator_y)))


def _feature_value(feature, name, default):
    if feature is None:
        return default

    if isinstance(feature, dict):
        return feature.get(name, default)

    return getattr(feature, name, default)
