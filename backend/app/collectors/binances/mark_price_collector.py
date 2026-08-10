import time
from datetime import datetime

import requests

from app.utils.network_resilience import classify_network_error
from app.utils.network_resilience import is_transient_network_error


class MarkPriceCollector:
    URL = "https://fapi.binance.com/fapi/v1/markPriceKlines"

    def get_klines(
        self,
        symbol,
        timeframe,
        *,
        limit=2,
        start_time_ms=None,
        end_time_ms=None,
    ):
        last_error = None
        for _attempt in range(3):
            try:
                params = {
                    "symbol": symbol,
                    "interval": timeframe,
                    "limit": min(max(int(limit), 1), 1500),
                }
                if start_time_ms is not None:
                    params["startTime"] = int(start_time_ms)
                if end_time_ms is not None:
                    params["endTime"] = int(end_time_ms)
                response = requests.get(
                    self.URL,
                    params=params,
                    timeout=20,
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, list):
                    return []
                now_ms = int(time.time() * 1000)
                return [
                    parsed
                    for row in payload
                    if (parsed := _parse_mark_price_kline(symbol, timeframe, row, now_ms))
                    is not None
                ]
            except Exception as ex:
                last_error = ex
                time.sleep(3)

        if last_error is not None and not is_transient_network_error(last_error):
            print(
                f"Mark price error {symbol} {timeframe}: "
                f"{classify_network_error(last_error)}"
            )
        return []


def _parse_mark_price_kline(symbol, timeframe, row, now_ms):
    if not isinstance(row, (list, tuple)) or len(row) < 7:
        return None
    try:
        open_time_ms = int(row[0])
        close_time_ms = int(row[6])
        if close_time_ms > now_ms:
            return None
        return {
            "venue": "BINANCE",
            "market_type": "USDT_FUTURES",
            "symbol": symbol,
            "timeframe": timeframe,
            "open_time": datetime.utcfromtimestamp(open_time_ms / 1000),
            "close_time": datetime.utcfromtimestamp(close_time_ms / 1000),
            "open_price": float(row[1]),
            "high_price": float(row[2]),
            "low_price": float(row[3]),
            "close_price": float(row[4]),
            "is_final": True,
            "source": "BINANCE_MARK_PRICE_KLINES",
        }
    except (TypeError, ValueError, OverflowError):
        return None
