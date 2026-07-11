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
    ordered_candles = candles
    data = calculate_trend(ordered_candles)
    trend_score = data["trend_score"]
    trend = data["trend"]
    momentum_score = data["momentum_score"]
    # print(f"trend_score : {trend_score}, trend : {trend}, Momentum : {momentum_score}")
    # momentum_score = calculate_momentum(ordered_candles)
    # Updated timeframe-aware, symbol-relative candle metrics.

    volatility_score, atr, volatility_data, *_ = calculate_volatility(
        symbol=symbol,
        timeframe=timeframe,
        candles=ordered_candles,
    )

    liquidity_score, liquidity_data = calculate_liquidity(
        symbol=symbol,
        timeframe=timeframe,
        candles=ordered_candles,
    )
    # volatility_score, atr = calculate_volatility(ordered_candles)
    # liquidity_score = calculate_liquidity(ordered_candles)
    # print(f"trend_score : {trend_score}")

    # Volatility intensity is converted to suitability because higher
    # volatility does not mean a more bullish market.
    volatility_suitability_score = calculate_volatility_suitability(volatility_score)

    # Direction comes only from directional indicators.
    directional_score = trend_score * 0.55 + momentum_score * 0.45
    # Market conditions control signal conviction, not signal direction.
    market_quality_score = liquidity_score * 0.65 + volatility_suitability_score * 0.35

    # Poor market quality pulls the directional score toward neutral 50.
    # Multiplier range: 0.60 to 1.00.
    conviction_multiplier = 0.60 + (market_quality_score / 100.0) * 0.40

    final_score = 50.0 + (directional_score - 50.0) * conviction_multiplier
    final_score = round(clamp(final_score, 0.0, 100.0), 2)
    directional_score = round(directional_score, 2)
    market_quality_score = round(market_quality_score, 2)
    conviction_multiplier = round(conviction_multiplier, 4)

    if final_score > 70.0:
        signal = "BUY"
    elif final_score < 40.0:
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
        "trend_score": round(trend_score, 2),
        "momentum_score": round(momentum_score, 2),
        "volatility_score": round(volatility_score, 2),
        "volatility_suitability_score": volatility_suitability_score,
        "liquidity_score": round(liquidity_score, 2),
        "atr": round(atr, 8),
        "trend": trend,
        "directional_score": directional_score,
        "market_quality_score": market_quality_score,
        "conviction_multiplier": conviction_multiplier,
        "final_score": final_score,
        "signal": signal,
        "quality": quality,
        "sentiment_score": quality.get("sentiment_score", 50.0),
        "correlation_score": quality.get("correlation_score", 50.0),
        "quality_score": quality.get("quality_score", 50.0),
        "quality_bias": quality.get("quality_bias", "NEUTRAL"),
        "volatility": volatility_data.get("volatility", "UNKNOWN"),
        "liquidity": liquidity_data.get("liquidity", "UNKNOWN"),
        "volatility_data_confidence": volatility_data.get("data_confidence", 0.0),
        "liquidity_data_confidence": liquidity_data.get("data_confidence", 0.0),
        "volatility_is_usable": volatility_data.get("is_usable", False),
        "liquidity_is_usable": liquidity_data.get("is_usable", False),
        "volatility_details": volatility_data,
        "liquidity_details": liquidity_data,
    }


def calculate_volatility_suitability(volatility_score: float) -> float:
    """
    Convert volatility intensity into trading suitability.

    Volatility itself is not bullish or bearish. Moderate/high-but-controlled
    volatility is generally more usable than extremely low or extreme
    volatility.

    Peak suitability is around a volatility score of 55.
    """
    score = 100.0 - abs(float(volatility_score) - 55.0) * 1.6
    return round(clamp(score, 0.0, 100.0), 2)


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(value, maximum))
