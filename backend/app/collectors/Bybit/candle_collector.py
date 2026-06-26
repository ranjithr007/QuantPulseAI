import requests
import time

from datetime import datetime

from app.utils.network_resilience import classify_network_error
from app.utils.network_resilience import is_transient_network_error


class CandleCollector:

    BASE_URL = "https://api.bybit.com"

    def get_candles(self, symbol, interval="5m", limit=100):

        url = f"{self.BASE_URL}/v5/market/kline"

        params = {"symbol": symbol, "interval": interval, "limit": limit}

        last_error = None

        for attempt in range(3):

            try:

                response = requests.get(url, params=params, timeout=20)

                response.raise_for_status()

                payload = response.json()
                if isinstance(payload, list):
                    rows = payload
                elif isinstance(payload, dict):
                    rows = (
                        payload.get("result", {}).get("list")
                        or payload.get("result", {}).get("data")
                        or payload.get("data")
                        or []
                    )
                else:
                    rows = []

                candles = []

                for x in rows:

                    if isinstance(x, dict):
                        x = [
                            x.get("open_time") or x.get("openTime") or x.get("startTime"),
                            x.get("open"),
                            x.get("high"),
                            x.get("low"),
                            x.get("close"),
                            x.get("volume"),
                        ]

                    if len(x) < 6:
                        continue

                    open_time_ms = int(x[0])

                    candles.append(
                        {
                            "symbol": symbol,
                            "timeframe": interval,
                            "open_time_ms": open_time_ms,
                            "open_time": datetime.fromtimestamp(open_time_ms / 1000),
                            "open": float(x[1]),
                            "high": float(x[2]),
                            "low": float(x[3]),
                            "close": float(x[4]),
                            "volume": float(x[5]),
                        }
                    )

                candles.sort(key=lambda item: item["open_time_ms"])
                return candles

            except Exception as ex:
                last_error = ex
                time.sleep(_retry_delay_seconds(attempt + 1))

        if last_error is not None:
            if not is_transient_network_error(last_error):
                print(f"Candle error {symbol}: {classify_network_error(last_error)}")

        return []


def _retry_delay_seconds(attempt_number):
    return min(30, 3 * (2 ** min(max(attempt_number - 1, 0), 4)))
