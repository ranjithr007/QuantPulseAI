import requests
import time

from datetime import datetime
from datetime import timezone

from app.utils.network_resilience import classify_network_error
from app.utils.network_resilience import is_transient_network_error
from app.utils.timeframes import candle_is_final
from app.utils.timeframes import normalized_close_boundary_ms
from app.utils.timeframes import timeframe_seconds


class CandleCollector:

    BASE_URL = "https://api.bybit.com"
    MAX_PAGE_SIZE = 1000
    INTERVALS = {
        "1m": "1",
        "5m": "5",
        "15m": "15",
        "1h": "60",
        "4h": "240",
        "1d": "D",
    }

    def get_candles(
        self,
        symbol,
        interval="5m",
        limit=100,
        start_time_ms=None,
        end_time_ms=None,
    ):
        requested_limit = max(int(limit or 0), 0)
        if not requested_limit:
            return []

        url = f"{self.BASE_URL}/v5/market/kline"
        bybit_interval = self.INTERVALS.get(interval, interval)
        interval_ms = timeframe_seconds(interval) * 1000
        cursor_start = (
            int(start_time_ms) if start_time_ms is not None else None
        )
        cursor_end = int(end_time_ms) if end_time_ms is not None else None
        collected = {}

        while len(collected) < requested_limit:
            page_limit = min(
                requested_limit - len(collected),
                self.MAX_PAGE_SIZE,
            )
            params = {
                "category": "linear",
                "symbol": symbol,
                "interval": bybit_interval,
                "limit": page_limit,
            }
            if cursor_start is not None:
                params["start"] = cursor_start
            if cursor_end is not None:
                params["end"] = cursor_end

            rows = self._get_page(url, params, symbol)
            if not rows:
                break

            page_candles = self._parse_rows(symbol, interval, rows)
            if not page_candles:
                break

            previous_count = len(collected)
            for candle in page_candles:
                if (
                    start_time_ms is not None
                    and candle["open_time_ms"] < int(start_time_ms)
                ):
                    continue
                if (
                    end_time_ms is not None
                    and candle["open_time_ms"] > int(end_time_ms)
                ):
                    continue
                collected[candle["open_time_ms"]] = candle

            latest_open_time = max(
                candle["open_time_ms"] for candle in page_candles
            )
            if (
                len(collected) == previous_count
                or len(page_candles) < page_limit
                or cursor_start is None
            ):
                break

            next_cursor_start = latest_open_time + interval_ms
            if next_cursor_start <= cursor_start:
                break
            if cursor_end is not None and next_cursor_start > cursor_end:
                break
            cursor_start = next_cursor_start

        candles = sorted(
            collected.values(),
            key=lambda item: item["open_time_ms"],
        )
        return candles[-requested_limit:]

    @staticmethod
    def _get_page(url, params, symbol):
        last_error = None

        for attempt in range(3):
            try:
                response = requests.get(url, params=params, timeout=20)
                response.raise_for_status()
                payload = response.json()
                if isinstance(payload, list):
                    return payload
                if isinstance(payload, dict):
                    return (
                        payload.get("result", {}).get("list")
                        or payload.get("result", {}).get("data")
                        or payload.get("data")
                        or []
                    )
                return []
            except Exception as ex:
                last_error = ex
                time.sleep(_retry_delay_seconds(attempt + 1))

        if last_error is not None:
            if not is_transient_network_error(last_error):
                print(
                    f"Candle error {symbol}: "
                    f"{classify_network_error(last_error)}"
                )
        return []

    @staticmethod
    def _parse_rows(symbol, interval, rows):
        candles = []
        now_ms = int(time.time() * 1000)

        for row in rows:
            exchange_close_time_ms = None
            if isinstance(row, dict):
                exchange_close_time_ms = (
                    row.get("close_time")
                    or row.get("closeTime")
                    or row.get("endTime")
                )
                row = [
                    row.get("open_time")
                    or row.get("openTime")
                    or row.get("startTime"),
                    row.get("open"),
                    row.get("high"),
                    row.get("low"),
                    row.get("close"),
                    row.get("volume"),
                    exchange_close_time_ms,
                ]
            if not isinstance(row, (list, tuple)) or len(row) < 6:
                continue
            try:
                    open_time_ms = int(row[0])
                    close_time_ms = normalized_close_boundary_ms(
                        open_time_ms,
                        interval,
                        exchange_close_time_ms,
                    )

                    candles.append(
                        {
                            "symbol": symbol,
                            "timeframe": interval,
                            "venue": "BYBIT",
                            "market_type": "FUTURES",
                            "source": "BYBIT_FUTURES_REST",
                            "open_time_ms": open_time_ms,
                            "close_time_ms": close_time_ms,
                            "open_time": datetime.fromtimestamp(
                                open_time_ms / 1000,
                                timezone.utc,
                            ),
                            "close_time": datetime.fromtimestamp(
                                close_time_ms / 1000,
                                timezone.utc,
                            ),
                            "is_final": candle_is_final(close_time_ms, now_ms),
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


def _retry_delay_seconds(attempt_number):
    return min(30, 3 * (2 ** min(max(attempt_number - 1, 0), 4)))
