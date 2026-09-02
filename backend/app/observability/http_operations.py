"""Small dependency-free HTTP operations helpers for cloud runtimes."""

import json
import logging
import sys
import threading
import time
from collections import OrderedDict, deque
from datetime import datetime, timezone


class SlidingWindowRateLimiter:
    def __init__(self, max_keys=10_000):
        self._max_keys = max(1, int(max_keys))
        self._events = OrderedDict()
        self._lock = threading.Lock()

    def allow(self, key, limit, window_seconds=60, now=None):
        current = time.monotonic() if now is None else float(now)
        cutoff = current - float(window_seconds)
        with self._lock:
            events = self._events.get(key)
            if events is None:
                while len(self._events) >= self._max_keys:
                    self._events.popitem(last=False)
                events = deque()
                self._events[key] = events
            else:
                self._events.move_to_end(key)
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= int(limit):
                return False
            events.append(current)
            return True


class JsonLogFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update(getattr(record, "structured", {}) or {})
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, separators=(",", ":"))


def build_http_logger():
    logger = logging.getLogger("quantpulse.http")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonLogFormatter())
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger
