def clamp(value, minimum, maximum):
    return max(minimum, min(value, maximum))


def calculate_delta(candles):
    """
    Estimate buy/sell volume from candle close position.

    Returns:
        buy_volume
        sell_volume
        delta
        delta_pct
        candle_deltas
    """

    buy_volume = 0.0
    sell_volume = 0.0
    candle_deltas = []

    for candle in candles:
        high = float(candle.high_price or 0)
        low = float(candle.low_price or 0)
        close = float(candle.close_price or 0)
        volume = float(candle.volume or 0)

        candle_range = high - low

        if volume <= 0:
            candle_deltas.append(0.0)
            continue

        if candle_range <= 0:
            estimated_buy_volume = volume * 0.50
            estimated_sell_volume = volume * 0.50
        else:
            # Close near high = stronger estimated buying pressure.
            # Close near low = stronger estimated selling pressure.
            buy_ratio = (close - low) / candle_range
            buy_ratio = clamp(buy_ratio, 0.0, 1.0)

            estimated_buy_volume = volume * buy_ratio
            estimated_sell_volume = volume * (1.0 - buy_ratio)

        candle_delta = estimated_buy_volume - estimated_sell_volume

        buy_volume += estimated_buy_volume
        sell_volume += estimated_sell_volume
        candle_deltas.append(candle_delta)

    total_volume = buy_volume + sell_volume
    delta = buy_volume - sell_volume

    delta_pct = (delta / total_volume) * 100 if total_volume > 0 else 0.0

    return {
        "buy_volume": buy_volume,
        "sell_volume": sell_volume,
        "total_volume": total_volume,
        "delta": delta,
        "delta_pct": delta_pct,
        "candle_deltas": candle_deltas,
    }


def detect_absorption(delta_pct, price_change_pct):
    """
    Detect opposite-side absorption.

    Positive delta but no upward price progress:
        passive sellers may be absorbing market buyers.

    Negative delta but no downward price progress:
        passive buyers may be absorbing market sellers.
    """

    minimum_delta_pct = 15.0
    maximum_price_progress_pct = 0.10

    if delta_pct >= minimum_delta_pct:
        if price_change_pct <= maximum_price_progress_pct:
            return "SELLER_ABSORPTION"

    if delta_pct <= -minimum_delta_pct:
        if price_change_pct >= -maximum_price_progress_pct:
            return "BUYER_ABSORPTION"

    return "NONE"


def detect_exhaustion(candle_deltas):
    """
    Simple exhaustion estimate based on the last three candle deltas.

    Buyer exhaustion:
        positive delta is becoming progressively weaker.

    Seller exhaustion:
        negative delta is becoming progressively weaker.
    """

    if len(candle_deltas) < 3:
        return "NONE"

    previous_2 = candle_deltas[-3]
    previous_1 = candle_deltas[-2]
    current = candle_deltas[-1]

    # Buying remains positive but is weakening.
    if previous_2 > previous_1 > current > 0:
        return "BUYER_EXHAUSTION"

    # Selling remains negative but is weakening toward zero.
    if previous_2 < previous_1 < current < 0:
        return "SELLER_EXHAUSTION"

    return "NONE"


def analyze_orderflow(
    candles,
    previous_cvd=0.0,
    use_persistent_cvd=False,
):
    """
    Returns all fields required by MarketOrderFlow.

    Important:
    use_persistent_cvd=True only when candles contain new,
    non-overlapping data.
    """

    if not candles:
        return {
            "buy_volume": 0.0,
            "sell_volume": 0.0,
            "delta": 0.0,
            "cvd": previous_cvd,
            "buyer_strength": 50.0,
            "seller_strength": 50.0,
            "absorption": "NONE",
            "exhaustion": "NONE",
            "signal": "NEUTRAL",
            "confidence": 0.0,
        }

    delta_data = calculate_delta(candles)

    buy_volume = delta_data["buy_volume"]
    sell_volume = delta_data["sell_volume"]
    total_volume = delta_data["total_volume"]
    delta = delta_data["delta"]
    delta_pct = delta_data["delta_pct"]
    candle_deltas = delta_data["candle_deltas"]

    first_price = float(candles[0].open_price or 0)
    last_price = float(candles[-1].close_price or 0)

    price_change = last_price - first_price

    price_change_pct = (price_change / first_price) * 100 if first_price > 0 else 0.0

    # Strength based directly on estimated volume percentages.
    if total_volume > 0:
        buyer_strength = (buy_volume / total_volume) * 100
        seller_strength = (sell_volume / total_volume) * 100
    else:
        buyer_strength = 50.0
        seller_strength = 50.0

    absorption = detect_absorption(
        delta_pct=delta_pct,
        price_change_pct=price_change_pct,
    )

    exhaustion = detect_exhaustion(candle_deltas)

    signal = "NEUTRAL"

    if absorption == "SELLER_ABSORPTION":
        signal = "POSSIBLE_SELL_REVERSAL"

    elif absorption == "BUYER_ABSORPTION":
        signal = "POSSIBLE_BUY_REVERSAL"

    elif buyer_strength >= 60:
        signal = "BUYERS_CONTROL"

    elif seller_strength >= 60:
        signal = "SELLERS_CONTROL"

    # Base confidence from volume imbalance.
    confidence = clamp(abs(delta_pct) * 2.5, 0.0, 100.0)

    # Increase confidence when price confirms delta.
    price_confirms_delta = (delta > 0 and price_change > 0) or (
        delta < 0 and price_change < 0
    )

    if price_confirms_delta:
        confidence += 10.0

    # Absorption means delta and price are conflicting.
    if absorption != "NONE":
        confidence *= 0.80

    # Weakening pressure reduces control-signal confidence.
    if exhaustion != "NONE":
        confidence *= 0.85

    confidence = clamp(confidence, 0.0, 100.0)

    if use_persistent_cvd:
        # Use only for new, non-overlapping candle/trade data.
        cvd = previous_cvd + delta
    else:
        # CVD for the supplied candle window.
        cvd = sum(candle_deltas)

    return {
        "buy_volume": round(buy_volume, 8),
        "sell_volume": round(sell_volume, 8),
        "delta": round(delta, 8),
        "cvd": round(cvd, 8),
        "buyer_strength": round(buyer_strength, 2),
        "seller_strength": round(seller_strength, 2),
        "absorption": absorption,
        "exhaustion": exhaustion,
        "signal": signal,
        "confidence": round(confidence, 2),
        # Additional fields useful for debugging.
        "delta_pct": round(delta_pct, 4),
        "price_change": round(price_change, 8),
        "price_change_pct": round(price_change_pct, 4),
        "total_volume": round(total_volume, 8),
    }