from app.features.trend_features import calculate_trend
from app.features.momentum_features import calculate_momentum
from app.features.volatility_features import calculate_volatility
from app.features.liquidity_features import calculate_liquidity


def build_features(symbol, timeframe, candles):

    trend_score, trend = calculate_trend(candles)

    momentum_score = calculate_momentum(candles)

    volatility_score, atr = calculate_volatility(candles)

    liquidity_score = calculate_liquidity(candles)

    final_score = (
        trend_score * 0.35
        + momentum_score * 0.35
        + volatility_score * 0.15
        + liquidity_score * 0.15
    )

    if final_score > 70:

        signal = "BUY"

    elif final_score < 40:

        signal = "SELL"

    else:

        signal = "WAIT"

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
    }