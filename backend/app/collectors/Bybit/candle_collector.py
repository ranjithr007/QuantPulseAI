import requests
import time

from datetime import datetime


class CandleCollector:

    BASE_URL = "https://api.bybit.com"

    def get_candles(self, symbol, interval="5m", limit=100):

        url = f"{self.BASE_URL}/v5/market/kline"

        params = {"symbol": symbol, "interval": interval, "limit": limit}

        for attempt in range(3):
             
            try:

                response = requests.get(url, params=params, timeout=20)

                response.raise_for_status()

                data = response.json()

                candles = []

                for x in data:

                    # print(data)
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

                # time.sleep(3)

        return []