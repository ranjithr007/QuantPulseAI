from typing import List


def calculate_trend(candles):
    """
    Returns:
        trend_score: 0-100
        trend: STRONG_BULLISH, BULLISH, SIDEWAYS,
               BEARISH, or STRONG_BEARISH
        trend details
    """

    if not candles or len(candles) < 50:
        return {
            "trend_score": 50.0,
            "trend": "UNKNOWN",
            "ema20": None,
            "ema50": None,
            "ema_gap_pct": 0.0,
            "price_position": "UNKNOWN",
            "momentum_score": 0.0,
        }

    closes = [float(c.close_price) for c in candles]

    current_price = closes[-1]

    ema20 = calculate_ema(closes, 20)
    ema50 = calculate_ema(closes, 50)

    if ema50 == 0:
        ema_gap_pct = 0.0
    else:
        ema_gap_pct = ((ema20 - ema50) / ema50) * 100

    score = 50.0

    # EMA relationship: maximum contribution +/-25.
    ema_component = clamp(ema_gap_pct * 10, -25, 25)
    score += ema_component

    # Current price relative to EMA20.
    if current_price > ema20:
        score += 10
        price_position = "ABOVE_EMA20"
    elif current_price < ema20:
        score -= 10
        price_position = "BELOW_EMA20"
    else:
        price_position = "AT_EMA20"

    # Current price relative to EMA50.
    if current_price > ema50:
        score += 10
    elif current_price < ema50:
        score -= 10

    score = clamp(score, 0, 100)

    if score >= 75:
        trend = "STRONG_BULLISH"
    elif score >= 60:
        trend = "BULLISH"
    elif score <= 25:
        trend = "STRONG_BEARISH"
    elif score <= 40:
        trend = "BEARISH"
    else:
        trend = "SIDEWAYS"

    momentum_score = getmomentum_score(closes, 5)
    return {"trend_score": score, "trend": trend, "momentum_score": momentum_score}


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(value, maximum))


def calculate_ema(values, period: int) -> float:
    """
    Calculate the latest EMA value.

    Requires at least `period` values.
    """

    if len(values) < period:
        raise ValueError(f"At least {period} values are required to calculate EMA.")

    multiplier = 2 / (period + 1)

    # Use SMA as the initial EMA value.
    ema = sum(values[:period]) / period

    for value in values[period:]:
        ema = ((value - ema) * multiplier) + ema

    return ema


def getmomentum_score(closes: List[float], lookback: int = 5) -> float:
    """
    Short-term momentum: percentage change over the last `lookback` bars,
    clamped and scaled to a ±10 contribution.

    A 2 % move → full ±10 points.
    """
    if len(closes) < lookback + 1:
        return 0.0
    pct_change = (closes[-1] - closes[-lookback - 1]) / closes[-lookback - 1] * 100
    return clamp(pct_change * 5, -10, 10)
