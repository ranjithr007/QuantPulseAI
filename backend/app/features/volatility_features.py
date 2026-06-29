from typing import Any
from app.features.feature_market_metrics import calculate_volatility_metrics

def calculate_volatility(
    symbol: str,
    timeframe: str,
    candles,
) -> tuple[float, float, dict[str, Any]]:
    """Return volatility score, ATR and the complete metrics response."""
    data = calculate_volatility_metrics(
        candles=candles,
        symbol=symbol,
        timeframe=timeframe,
    )

    # Insufficient/invalid candle data should remain neutral, not bullish/bearish.
    volatility_score = (
        float(data.get("volatility_score", 50.0))
        if data.get("is_usable", False)
        else 50.0
    )

    atr_value = data.get("atr")
    atr = float(atr_value) if atr_value is not None else 0.0

    return volatility_score, atr, data

