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

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=lambda: asyncio.run(self._run()), daemon=True, name="paper-exit-prices")
            self._thread.start()

    def stop(self):
        self._stop.set()

    def ingest(self, payload, now=None):
        now = now or datetime.now(timezone.utc)
        if not isinstance(payload, list):
            return
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
                except (KeyError, TypeError, ValueError, OverflowError):
                    continue

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

    async def _run(self):
        while not self._stop.is_set():
            try:
                async with websockets.connect(STREAM_URL, open_timeout=5, ping_interval=20, ping_timeout=10, close_timeout=1) as socket:
                    while not self._stop.is_set():
                        raw = await asyncio.wait_for(socket.recv(), timeout=5)
                        self.ingest(json.loads(raw))
            except Exception:
                # Missing/stale quotes are surfaced by the exit job. Never
                # fabricate a current price or busy-loop on a disconnected feed.
                for _ in range(10):
                    if self._stop.is_set():
                        return
                    await asyncio.sleep(0.1)


paper_exit_prices = PaperExitPrices()
