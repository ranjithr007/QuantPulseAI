"""Worker-owned one-second futures marks; no orders and no per-trade REST calls."""
import asyncio
import json
import math
import threading
from collections import defaultdict, deque
from datetime import datetime, timezone

import websockets


STREAM_URL = "wss://fstream.binance.com/market/ws/!markPrice@arr@1s"
MAX_PRICE_AGE_SECONDS = 5


class PaperExitPrices:
    def __init__(self):
        self._lock = threading.Lock()
        self._thread = None
        self._stop = threading.Event()
        self._pending = defaultdict(lambda: deque(maxlen=10))
        self._latest = {}
        self._connected = False
        self._last_message_at = None
        self._last_error = None

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=lambda: asyncio.run(self._run()), daemon=True, name="paper-exit-prices")
            self._thread.start()

    def stop(self):
        self._stop.set()
        with self._lock:
            self._connected = False

    def ingest(self, payload, now=None):
        now = now or datetime.now(timezone.utc)
        if not isinstance(payload, list):
            return
        accepted = 0
        with self._lock:
            for item in payload:
                try:
                    symbol = str(item["s"]).upper()
                    price = float(item["p"])
                    observed = datetime.fromtimestamp(int(item["E"]) / 1000, timezone.utc)
                    age = (now - observed).total_seconds()
                    if not symbol or not math.isfinite(price) or price <= 0 or not -1 <= age <= MAX_PRICE_AGE_SECONDS:
                        continue
                    previous = self._latest.get(symbol)
                    if previous and observed <= previous["observed_at"]:
                        continue
                    mark = {"symbol": symbol, "mark_price": price, "observed_at": observed, "source": "BINANCE_MARK_STREAM_1S"}
                    self._latest[symbol] = mark
                    self._pending[symbol].append(mark)
                    accepted += 1
                except (KeyError, TypeError, ValueError, OverflowError):
                    continue
            if accepted:
                # Receiving a valid frame is stronger evidence than merely
                # completing the websocket handshake.
                self._connected = True
                self._last_message_at = now
                self._last_error = None

    def health(self, now=None, max_age_seconds=MAX_PRICE_AGE_SECONDS):
        """Report whether the Binance stream can protect a newly opened trade."""
        now = now or datetime.now(timezone.utc)
        with self._lock:
            connected = self._connected
            last_message_at = self._last_message_at
            last_error = self._last_error
            thread_alive = bool(self._thread and self._thread.is_alive())

        message_age = (
            max(0.0, (now - last_message_at).total_seconds())
            if last_message_at is not None
            else None
        )
        fresh = message_age is not None and message_age <= float(max_age_seconds)
        ready = connected and fresh and not last_error
        if not connected:
            reason = "Binance mark stream is disconnected"
        elif last_message_at is None:
            reason = "Binance mark stream has not delivered a valid message"
        elif not fresh:
            reason = (
                f"Binance mark stream is stale ({message_age:.2f}s old; "
                f"limit {float(max_age_seconds):.2f}s)"
            )
        elif last_error:
            reason = f"Binance mark stream error: {last_error}"
        else:
            reason = None

        return {
            "policy": "BINANCE_MARK_STREAM_HEALTH_V1",
            "ready": ready,
            "connected": connected,
            "reason": reason,
            "max_age_seconds": float(max_age_seconds),
            "message_age_seconds": round(message_age, 3) if message_age is not None else None,
            "last_message_at": last_message_at.isoformat() if last_message_at is not None else None,
            "last_error": last_error,
            "thread_alive": thread_alive,
        }

    def take(self, symbols, now=None):
        now = now or datetime.now(timezone.utc)
        result = {}
        with self._lock:
            for symbol in set(symbols):
                pending = self._pending.pop(symbol, ())
                latest = self._latest.get(symbol)
                marks = list(pending) or ([latest] if latest else [])
                result[symbol] = [mark for mark in marks if -1 <= (now - mark["observed_at"]).total_seconds() <= MAX_PRICE_AGE_SECONDS]
            # Only retain pending ticks for currently open coins. Latest prices
            # remain available for a new position without resubscribing.
            self._pending.clear()
        return result

    def latest(self, symbols, now=None):
        """Return fresh last-known marks without consuming pending exit ticks."""
        now = now or datetime.now(timezone.utc)
        result = {}
        with self._lock:
            for raw_symbol in set(symbols):
                symbol = str(raw_symbol or "").upper()
                mark = self._latest.get(symbol)
                if mark is None:
                    result[symbol] = None
                    continue
                age = (now - mark["observed_at"]).total_seconds()
                result[symbol] = mark if -1 <= age <= MAX_PRICE_AGE_SECONDS else None
        return result

    async def _run(self):
        while not self._stop.is_set():
            try:
                async with websockets.connect(STREAM_URL, open_timeout=5, ping_interval=20, ping_timeout=10, close_timeout=1) as socket:
                    with self._lock:
                        self._connected = True
                        # Keep any disconnect error until a valid frame arrives;
                        # a handshake alone does not prove usable live pricing.
                    while not self._stop.is_set():
                        raw = await asyncio.wait_for(socket.recv(), timeout=5)
                        self.ingest(json.loads(raw))
            except Exception as exc:
                # Missing/stale quotes are surfaced by the exit job. Never
                # fabricate a current price or busy-loop on a disconnected feed.
                with self._lock:
                    self._connected = False
                    self._last_error = type(exc).__name__
                for _ in range(10):
                    if self._stop.is_set():
                        return
                    await asyncio.sleep(0.1)
        with self._lock:
            self._connected = False


paper_exit_prices = PaperExitPrices()
