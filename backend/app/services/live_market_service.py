import asyncio
import json
from datetime import datetime
from datetime import timezone

import websockets


BINANCE_STREAM_URL = "wss://stream.binance.com:9443/stream"
DEFAULT_LIVE_SYMBOLS = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT"]
LIVE_STALE_AFTER_SECONDS = 15


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

    def start(self, symbols=None):
        if self._task and not self._task.done():
            return True

        self._stopping = False
        selected_symbols = _normalize_symbols(symbols or DEFAULT_LIVE_SYMBOLS)
        self._symbols = selected_symbols
        self._started_at = _utc_now()
        self._last_error = None
        self._task = asyncio.create_task(self._run(selected_symbols))
        return True

    def status(self):
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
                self._last_error = f"{type(exc).__name__}: {exc}"
                self._reconnect_count += 1
                print(f"Live market websocket error: {exc}")
                await asyncio.sleep(5)

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


live_market_service = LiveMarketService()


def get_live_market_service():
    return live_market_service


def start_live_market_listener(symbols=None):
    return live_market_service.start(symbols)


async def stop_live_market_listener():
    await live_market_service.stop()
