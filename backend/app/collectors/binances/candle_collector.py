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

    URL = "https://fapi.binance.com/fapi/v1/klines"
    MAX_PAGE_SIZE = 1500

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

        collected = {}
        cursor_start = (
            int(start_time_ms) if start_time_ms is not None else None
        )
        cursor_end = int(end_time_ms) if end_time_ms is not None else None
        forward = cursor_start is not None
        interval_ms = timeframe_seconds(interval) * 1000

        while len(collected) < requested_limit:
            page_limit = min(requested_limit - len(collected), self.MAX_PAGE_SIZE)
            rows = self._get_page(
                symbol,
                interval,
                page_limit,
                start_time_ms=cursor_start,
                end_time_ms=cursor_end,
            )
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

            earliest_open_time = min(candle["open_time_ms"] for candle in page_candles)
            latest_open_time = max(candle["open_time_ms"] for candle in page_candles)
            if len(collected) == previous_count or len(page_candles) < page_limit:
                break

            if forward:
                next_cursor_start = latest_open_time + interval_ms
                if (
                    cursor_start is not None
                    and next_cursor_start <= cursor_start
                ):
                    break
                if cursor_end is not None and next_cursor_start > cursor_end:
                    break
                cursor_start = next_cursor_start
            else:
                next_cursor_end = earliest_open_time - 1
                if cursor_end is not None and next_cursor_end >= cursor_end:
                    break
                cursor_end = next_cursor_end

        candles = sorted(collected.values(), key=lambda item: item["open_time_ms"])
        return candles[-requested_limit:]

    def _get_page(
        self,
        symbol,
        interval,
        limit,
        start_time_ms=None,
        end_time_ms=None,
    ):

        params = {"symbol": symbol, "interval": interval, "limit": limit}
        if start_time_ms is not None:
            params["startTime"] = int(start_time_ms)
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
        now_ms = int(time.time() * 1000)

        for row in rows:
            if isinstance(row, dict):
                exchange_close_time_ms = (
                    row.get("close_time")
                    or row.get("closeTime")
                    or row.get("endTime")
                )
                row = [
                    row.get("open_time") or row.get("openTime") or row.get("startTime"),
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
                    row[6] if len(row) > 6 else None,
                )
                candles.append(
                    {
                        "symbol": symbol,
                        "timeframe": interval,
                        "venue": "BINANCE",
                        "market_type": "FUTURES",
                        "source": "BINANCE_FUTURES_REST",
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
