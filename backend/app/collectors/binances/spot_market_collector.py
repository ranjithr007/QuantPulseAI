"""Public Binance Spot market-data collector used for participation evidence."""

import time
from datetime import datetime
from datetime import timezone

import requests

from app.utils.network_resilience import classify_network_error
from app.utils.network_resilience import is_transient_network_error


class SpotMarketCollector:
    BASE_URL = "https://data-api.binance.vision/api/v3/klines"

    def get_klines(
        self,
        symbol,
        interval="1h",
        limit=60,
        *,
        start_time=None,
        end_time=None,
    ):
        last_error = None
        for attempt in range(2):
            try:
                params = {
                    "symbol": str(symbol).upper(),
                    "interval": interval,
                    "limit": max(1, min(int(limit), 1000)),
                }
                if start_time is not None:
                    params["startTime"] = _milliseconds(start_time)
                if end_time is not None:
                    params["endTime"] = _milliseconds(end_time)
                response = requests.get(
                    self.BASE_URL,
                    params=params,
                    timeout=10,
                )
                response.raise_for_status()
                return self._parse_final_klines(response.json(), symbol, interval)
            except Exception as exc:
                last_error = exc
                if attempt < 1:
                    time.sleep(1)

        if last_error is not None and not is_transient_network_error(last_error):
            print(
                f"Spot market error {symbol} {interval}: "
                f"{classify_network_error(last_error)}"
            )
        return []

    @staticmethod
    def _parse_final_klines(rows, symbol, interval, *, now=None):
        current_ms = int(
            ((now or datetime.now(timezone.utc)).timestamp()) * 1000
        )
        parsed = []
        for row in rows or []:
            if not isinstance(row, (list, tuple)) or len(row) < 11:
                continue
            close_time_ms = int(row[6])
            if close_time_ms >= current_ms:
                continue
            quote_volume = float(row[7] or 0)
            taker_buy_quote = float(row[10] or 0)
            taker_sell_quote = max(0.0, quote_volume - taker_buy_quote)
            parsed.append(
                {
                    "symbol": str(symbol).upper(),
                    "timeframe": interval,
                    "open_time": datetime.fromtimestamp(
                        int(row[0]) / 1000,
                        tz=timezone.utc,
                    ).replace(tzinfo=None),
                    "close_time": datetime.fromtimestamp(
                        close_time_ms / 1000,
                        tz=timezone.utc,
                    ).replace(tzinfo=None),
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "base_volume": float(row[5] or 0),
                    "quote_volume": quote_volume,
                    "trade_count": int(row[8] or 0),
                    "taker_buy_quote_volume": taker_buy_quote,
                    "taker_sell_quote_volume": taker_sell_quote,
                    "spot_delta_quote": taker_buy_quote - taker_sell_quote,
                    "is_final": True,
                    "source": "BINANCE_SPOT_KLINE",
                }
            )
        return parsed


def _milliseconds(value):
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, datetime):
        timestamp = value
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return int(timestamp.timestamp() * 1000)
    raise TypeError("start_time and end_time must be datetime or epoch milliseconds")
