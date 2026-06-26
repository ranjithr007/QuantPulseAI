from app.features.trend_features import calculate_trend
from app.features.momentum_features import calculate_momentum
from app.features.volatility_features import calculate_volatility
from app.features.liquidity_features import calculate_liquidity
from app.features.feature_quality_engine import build_feature_quality_profile


def order_candles_for_features(candles):
    if not candles:
        return []

    if all(
        hasattr(candle, "candle_time") and candle.candle_time is not None
        for candle in candles
    ):
        return sorted(candles, key=lambda candle: candle.candle_time)

    return list(candles)


def build_features(symbol, timeframe, candles):
    ordered_candles = order_candles_for_features(candles)

    trend_score, trend = calculate_trend(ordered_candles)

    momentum_score = calculate_momentum(ordered_candles)

    volatility_score, atr = calculate_volatility(ordered_candles)

    liquidity_score = calculate_liquidity(ordered_candles)
    
    # print(f"trend_score : {trend_score}")
    final_score = (
        trend_score * 0.35
        + momentum_score * 0.35
        + volatility_score * 0.15
        + liquidity_score * 0.15
    )

    # print(f"Final Score :{final_score}")

    if final_score > 70:

        signal = "BUY"

    elif final_score < 40:

        signal = "SELL"

    else:

        signal = "WAIT"
    quality = build_feature_quality_profile(
        db=None,
        symbol=symbol,
        timeframe=timeframe,
        candles=ordered_candles,
        feature={
            "TrendScore": trend_score,
            "MomentumScore": momentum_score,
            "VolatilityScore": volatility_score,
            "LiquidityScore": liquidity_score,
            "FinalScore": final_score,
            "Trend": trend,
            "ATR": atr,
        },
        benchmark_symbol=None,
        window=min(len(ordered_candles), 30) if ordered_candles else 30,
    )

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "trend_score": trend_score,
        "momentum_score": momentum_score,
        "volatility_score": volatility_score,
        "liquidity_score": liquidity_score,
        "atr": atr,
        "trend": trend,
        "final_score": final_score,
        "signal": signal,
        "quality": quality,
        "sentiment_score": quality["sentiment_score"],
        "correlation_score": quality["correlation_score"],
        "quality_score": quality["quality_score"],
        "quality_bias": quality["quality_bias"],
    }
