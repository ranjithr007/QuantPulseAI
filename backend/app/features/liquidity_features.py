from typing import Any
from app.features.feature_market_metrics import calculate_liquidity_metrics

def calculate_liquidity(
    symbol: str,
    timeframe: str,
    candles,
) -> tuple[float, dict[str, Any]]:
    """Return candle-liquidity score and the complete metrics response."""
    data = calculate_liquidity_metrics(
        candles=candles,
        symbol=symbol,
        timeframe=timeframe,
    )

    # Insufficient/invalid candle data should remain neutral.
    liquidity_score = (
        float(data.get("liquidity_score", 50.0))
        if data.get("is_usable", False)
        else 50.0
    )

    return liquidity_score, data