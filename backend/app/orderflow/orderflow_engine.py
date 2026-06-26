from app.orderflow.delta_engine import calculate_delta
from app.orderflow.absorption_engine import detect_absorption


def analyze_orderflow(candles):

    delta_data = calculate_delta(candles)

    delta = delta_data["delta"]

    first = candles[0]
    last = candles[-1]

    price_change = last.close_price - first.close_price

    absorption = detect_absorption(delta, price_change)

    buyer_strength = 50
    seller_strength = 50

    if delta > 0:

        buyer_strength = 75
        seller_strength = 25

    elif delta < 0:

        buyer_strength = 25
        seller_strength = 75

    signal = "NEUTRAL"

    if buyer_strength > 70:

        signal = "BUYERS_CONTROL"

    if seller_strength > 70:

        signal = "SELLERS_CONTROL"

    return {
        **delta_data,
        "buyer_strength": buyer_strength,
        "seller_strength": seller_strength,
        "absorption": absorption,
        "signal": signal,
        "confidence": abs(buyer_strength - 50) * 2,
    }
