import asyncio
import json
import threading
from datetime import datetime
from datetime import timezone

import requests
import websockets

from app.utils.network_resilience import classify_network_error
from app.utils.network_resilience import is_transient_network_error
from app.utils.network_resilience import summarize_network_error


BINANCE_STREAM_URL = "wss://fstream.binance.com/stream"
BINANCE_TICKER_PRICE_URL = "https://fapi.binance.com/fapi/v1/ticker/price"
DEFAULT_LIVE_SYMBOLS = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT"]
LIVE_STALE_AFTER_SECONDS = 15
LIVE_CONNECT_TIMEOUT_SECONDS = 10
LIVE_REST_REFRESH_SECONDS = 10


class LiveMarketService:
    def __init__(self):
        self._records = {}
        self._subscribers = set()
        self._task = None
        self._stopping = False
        self._symbols = DEFAULT_LIVE_SYMBOLS
        self._connected = False
        self._last_message_at = None
        self._last_error = None
        self._reconnect_count = 0
        self._started_at = None
        self._seed_thread = None

    def start(self, symbols=None):
        selected_symbols = _normalize_symbols(symbols or DEFAULT_LIVE_SYMBOLS)

        if self._task and not self._task.done():
            if self._symbols == selected_symbols:
                return True

            self._task.cancel()
            self._task = None
            self._connected = False

        self._stopping = False
        self._symbols = selected_symbols
        self._started_at = _utc_now()
        self._last_error = None
        self._reconnect_count = 0
        self._trigger_rest_seed(selected_symbols)
        self._task = asyncio.create_task(self._run(selected_symbols))
        return True

    def status(self):
        if (
            self._connected
            and (
                not self._records
                or _age_seconds(self._last_message_at) is None
                or _age_seconds(self._last_message_at) > LIVE_REST_REFRESH_SECONDS
            )
        ):
            self._trigger_rest_seed(self._symbols)

        running = bool(self._task and not self._task.done())
        symbol_status = {
            symbol: _record_status(self._records.get(symbol), running, self._connected)
            for symbol in self._symbols
        }

        if not running:
            state = "STOPPED"
        elif self._connected and self._records:
            state = "LIVE" if all(item["state"] == "LIVE" for item in symbol_status.values()) else "PARTIAL"
        elif self._records:
            state = "RECONNECTING"
        else:
            state = "CONNECTING"

        return {
            "running": running,
            "connected": self._connected,
            "state": state,
            "symbols": self._symbols,
            "cached_count": len(self._records),
            "last_tick_at": self._last_message_at,
            "last_error": self._last_error,
            "reconnect_count": self._reconnect_count,
            "started_at": self._started_at,
            "symbol_status": symbol_status,
        }

    async def stop(self):
        self._stopping = True

        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        self._task = None
        self._connected = False

    def snapshot(self, symbols=None):
        if (
            not self._records
            or _age_seconds(self._last_message_at) is None
            or _age_seconds(self._last_message_at) > LIVE_REST_REFRESH_SECONDS
        ):
            self._trigger_rest_seed(self._symbols)

        selected = set(_normalize_symbols(symbols)) if symbols else None
        records = [_decorate_record(record) for record in self._records.values()]

        if selected:
            records = [record for record in records if record["symbol"] in selected]

        return sorted(records, key=lambda item: item["symbol"])

    def subscribe(self):
        queue = asyncio.Queue(maxsize=100)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue):
        self._subscribers.discard(queue)

    async def _run(self, symbols):
        streams = "/".join(f"{symbol.lower()}@kline_1m" for symbol in symbols)
        url = f"{BINANCE_STREAM_URL}?streams={streams}"

        while not self._stopping:
            try:
                async with websockets.connect(
                    url,
                    open_timeout=LIVE_CONNECT_TIMEOUT_SECONDS,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=5,
                ) as websocket:
                    self._connected = True
                    self._last_error = None
                    print("Live market websocket connected:", ", ".join(symbols))

                    try:
                        async for raw_message in websocket:
                            record = _record_from_message(raw_message)

                            if record:
                                self._records[record["symbol"]] = record
                                self._last_message_at = record["received_at"]
                                self._broadcast(record)
                    finally:
                        self._connected = False

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._connected = False
                self._last_error = summarize_network_error(exc)
                self._reconnect_count += 1
                delay = _reconnect_delay_seconds(self._reconnect_count)
                if not is_transient_network_error(exc):
                    print(
                        f"Live market websocket error: {self._last_error} "
                        f"(retrying in {delay}s)"
                    )
                await asyncio.sleep(delay)

    def _broadcast(self, record):
        for queue in list(self._subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass

            try:
                queue.put_nowait(record)
            except asyncio.QueueFull:
                pass

    def _seed_from_rest(self, symbols):
        selected_symbols = set(_normalize_symbols(symbols or self._symbols))
        if not selected_symbols:
            return

        try:
            response = requests.get(
                BINANCE_TICKER_PRICE_URL,
                timeout=3,
            )
            response.raise_for_status()
            payload = response.json() or []
        except Exception as exc:
            if self._last_error is None:
                self._last_error = summarize_network_error(exc)
            return

        received_at = _utc_now()

        for item in payload:
            symbol = str(item.get("symbol") or "").upper()
            if symbol not in selected_symbols:
                continue

            self._records[symbol] = {
                "source": "binance_futures_rest_ticker",
                "market_type": "FUTURES",
                "venue": "BINANCE_FUTURES",
                "symbol": symbol,
                "timeframe": "1m",
                "event_time": received_at,
                "candle_time": None,
                "current_price": _as_float(item.get("price")),
                "open_price": 0.0,
                "high_price": 0.0,
                "low_price": 0.0,
                "close_price": _as_float(item.get("price")),
                "volume": 0.0,
                "price_change_pct": None,
                "is_closed": False,
                "received_at": received_at,
            }

        if self._records:
            self._last_message_at = received_at

    def _trigger_rest_seed(self, symbols):
        if self._seed_thread and self._seed_thread.is_alive():
            return

        self._seed_thread = threading.Thread(
            target=self._seed_from_rest,
            args=(symbols,),
            daemon=True,
        )
        self._seed_thread.start()


def _record_from_message(raw_message):
    payload = json.loads(raw_message)
    data = payload.get("data", payload)

    if data.get("e") != "kline":
        return None

    candle = data.get("k") or {}
    open_price = _as_float(candle.get("o"))
    close_price = _as_float(candle.get("c"))
    price_change_pct = 0

    if open_price:
        price_change_pct = ((close_price - open_price) / open_price) * 100

    return {
        "source": "binance_ws_kline",
        "market_type": "FUTURES",
        "venue": "BINANCE_FUTURES",
        "symbol": data.get("s") or candle.get("s"),
        "timeframe": candle.get("i") or "1m",
        "event_time": _from_ms(data.get("E")),
        "candle_time": _from_ms(candle.get("t")),
        "current_price": close_price,
        "open_price": open_price,
        "high_price": _as_float(candle.get("h")),
        "low_price": _as_float(candle.get("l")),
        "close_price": close_price,
        "volume": _as_float(candle.get("v")),
        "price_change_pct": round(price_change_pct, 6),
        "is_closed": bool(candle.get("x")),
        "received_at": datetime.now(timezone.utc).isoformat(),
    }


def _normalize_symbols(symbols):
    if isinstance(symbols, str):
        symbols = symbols.split(",")

    return [symbol.strip().upper() for symbol in symbols if symbol and symbol.strip()]


def _decorate_record(record):
    decorated = dict(record)
    record_status = _record_status(record, running=True, connected=True)
    decorated["freshness_state"] = record_status["state"]
    decorated["age_seconds"] = record_status["age_seconds"]
    return decorated


def _record_status(record, running, connected):
    if not record:
        state = "WAITING" if running and connected else "UNAVAILABLE"
        return {"state": state, "last_tick_at": None, "age_seconds": None}

    last_tick_at = record.get("received_at") or record.get("event_time")
    age_seconds = _age_seconds(last_tick_at)
    state = "LIVE" if age_seconds is not None and age_seconds <= LIVE_STALE_AFTER_SECONDS else "STALE"
    return {
        "state": state,
        "last_tick_at": last_tick_at,
        "age_seconds": age_seconds,
    }


def _age_seconds(value):
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0, round((datetime.now(timezone.utc) - parsed).total_seconds(), 3))
    except (TypeError, ValueError):
        return None


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _from_ms(value):
    if value is None:
        return None

    return datetime.fromtimestamp(int(value) / 1000, timezone.utc).isoformat()


def _reconnect_delay_seconds(reconnect_count):
    return min(60, 5 * (2 ** min(max(reconnect_count - 1, 0), 4)))


live_market_service = LiveMarketService()


def get_live_market_service():
    return live_market_service


def start_live_market_listener(symbols=None):
    return live_market_service.start(symbols)


async def stop_live_market_listener():
    await live_market_service.stop()
