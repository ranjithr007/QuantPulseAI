import requests
import time

from datetime import datetime


class CandleCollector:

    URL = "https://api.binance.com/api/v3/klines"

    def get_candles(self, symbol, interval="5m", limit=100):

        params = {"symbol": symbol, "interval": interval, "limit": limit}

        for attempt in range(3):

            try:

                response = requests.get(self.URL, params=params, timeout=20)

                response.raise_for_status()

                data = response.json()

                candles = []

                for x in data:

                    candles.append(
                        {
                            "symbol": symbol,
                            "timeframe": interval,
                            "open_time_ms": x[0],
                            "open_time": datetime.fromtimestamp(x[0] / 1000),
                            "open": float(x[1]),
                            "high": float(x[2]),
                            "low": float(x[3]),
                            "close": float(x[4]),
                            "volume": float(x[5]),
                        }
                    )

                return candles

            except Exception as ex:

                print(f"Candle error {symbol}: {ex}")

                time.sleep(3)

        return []