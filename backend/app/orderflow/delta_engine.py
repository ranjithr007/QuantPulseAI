
def calculate_delta(candles):

    buy_volume = 0
    sell_volume = 0

    for candle in candles:

        if candle.close_price > candle.open_price:

            buy_volume += candle.volume

        else:

            sell_volume += candle.volume

    delta = buy_volume - sell_volume

    return {"buy_volume": buy_volume, "sell_volume": sell_volume, "delta": delta}