import requests
import time

from datetime import datetime

from app.utils.network_resilience import classify_network_error
from app.utils.network_resilience import is_transient_network_error


class CandleCollector:

    URL = "https://fapi.binance.com/fapi/v1/klines"
    MAX_PAGE_SIZE = 1500

    def get_candles(self, symbol, interval="5m", limit=100, end_time_ms=None):

        requested_limit = max(int(limit or 0), 0)
        if not requested_limit:
            return []

        collected = {}
        cursor_end = int(end_time_ms) if end_time_ms is not None else None

        while len(collected) < requested_limit:
            page_limit = min(requested_limit - len(collected), self.MAX_PAGE_SIZE)
            rows = self._get_page(
                symbol,
                interval,
                page_limit,
                end_time_ms=cursor_end,
            )
            if not rows:
                break

            page_candles = self._parse_rows(symbol, interval, rows)
            if not page_candles:
                break

            previous_count = len(collected)
            for candle in page_candles:
                collected[candle["open_time_ms"]] = candle

            earliest_open_time = min(candle["open_time_ms"] for candle in page_candles)
            if len(collected) == previous_count or len(page_candles) < page_limit:
                break

            next_cursor_end = earliest_open_time - 1
            if cursor_end is not None and next_cursor_end >= cursor_end:
                break
            cursor_end = next_cursor_end

        candles = sorted(collected.values(), key=lambda item: item["open_time_ms"])
        return candles[-requested_limit:]

    def _get_page(self, symbol, interval, limit, end_time_ms=None):

        params = {"symbol": symbol, "interval": interval, "limit": limit}
        if end_time_ms is not None:
            params["endTime"] = int(end_time_ms)
        last_error = None

        for attempt in range(3):

            try:

                response = requests.get(self.URL, params=params, timeout=20)

                response.raise_for_status()

                payload = response.json()
                if isinstance(payload, dict):
                    return payload.get("result", {}).get("list") or payload.get("data") or []
                return payload or []

            except Exception as ex:
                last_error = ex
                time.sleep(3)

        if last_error is not None:
            if not is_transient_network_error(last_error):
                print(f"Candle error {symbol}: {classify_network_error(last_error)}")

        return []

    @staticmethod
    def _parse_rows(symbol, interval, rows):
        candles = []

        for row in rows:
            if isinstance(row, dict):
                row = [
                    row.get("open_time") or row.get("openTime") or row.get("startTime"),
                    row.get("open"),
                    row.get("high"),
                    row.get("low"),
                    row.get("close"),
                    row.get("volume"),
                ]

            if not isinstance(row, (list, tuple)) or len(row) < 6:
                continue

            try:
                open_time_ms = int(row[0])
                candles.append(
                    {
                        "symbol": symbol,
                        "timeframe": interval,
                        "open_time_ms": open_time_ms,
                        "open_time": datetime.fromtimestamp(open_time_ms / 1000),
                        "open": float(row[1]),
                        "high": float(row[2]),
                        "low": float(row[3]),
                        "close": float(row[4]),
                        "volume": float(row[5]),
                    }
                )
            except (TypeError, ValueError):
                continue

        return candles
