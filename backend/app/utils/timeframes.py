TIMEFRAME_SECONDS = {
    "1m": 60,
    "5m": 5 * 60,
    "15m": 15 * 60,
    "1h": 60 * 60,
    "2h": 2 * 60 * 60,
    "4h": 4 * 60 * 60,
    "1d": 24 * 60 * 60,
}


def timeframe_seconds(timeframe):
    key = str(timeframe or "").strip().lower()
    if key not in TIMEFRAME_SECONDS:
        raise ValueError(f"Unsupported candle timeframe: {timeframe}")
    return TIMEFRAME_SECONDS[key]


def candle_close_boundary_ms(open_time_ms, timeframe):
    return int(open_time_ms) + timeframe_seconds(timeframe) * 1000


def normalized_close_boundary_ms(
    open_time_ms,
    timeframe,
    exchange_close_time_ms=None,
):
    if exchange_close_time_ms is None:
        return candle_close_boundary_ms(open_time_ms, timeframe)

    # Binance kline close timestamps are inclusive (boundary minus 1 ms).
    # Persist an exclusive boundary so finality is simply now >= close_time.
    value = int(exchange_close_time_ms)
    expected = candle_close_boundary_ms(open_time_ms, timeframe)
    if abs((value + 1) - expected) <= 1000:
        return value + 1
    return value


def candle_is_final(close_boundary_ms, now_ms):
    return int(now_ms) >= int(close_boundary_ms)
