import time
from datetime import datetime
from datetime import timezone

import requests

from app.utils.network_resilience import is_transient_network_error
from app.utils.network_resilience import summarize_network_error


class OrderBookCollector:
    URL = "https://fapi.binance.com/fapi/v1/depth"

    def get_snapshot(self, symbol, *, limit=100):
        last_error = None
        for attempt in range(2):
            try:
                response = requests.get(
                    self.URL,
                    params={
                        "symbol": str(symbol).upper(),
                        "limit": max(5, min(int(limit), 1000)),
                    },
                    timeout=10,
                )
                response.raise_for_status()
                return self.parse_snapshot(response.json(), symbol)
            except Exception as exc:
                last_error = exc
                if attempt < 1:
                    time.sleep(1)
        if last_error is not None and not is_transient_network_error(last_error):
            print(f"Order-book error {symbol}: {summarize_network_error(last_error)}")
        return None

    @staticmethod
    def parse_snapshot(payload, symbol, *, collected_at=None):
        bids = _levels((payload or {}).get("bids"))
        asks = _levels((payload or {}).get("asks"))
        if not bids or not asks:
            return None
        best_bid = max(price for price, _quantity in bids)
        best_ask = min(price for price, _quantity in asks)
        if best_bid <= 0 or best_ask <= 0 or best_ask < best_bid:
            return None
        mid = (best_bid + best_ask) / 2
        event_ms = (payload or {}).get("E") or (payload or {}).get("T")
        event_time = (
            datetime.fromtimestamp(int(event_ms) / 1000, tz=timezone.utc)
            if event_ms is not None
            else (collected_at or datetime.now(timezone.utc))
        ).replace(tzinfo=None)
        depths = {}
        for band in (0.5, 1.0, 2.0):
            lower = mid * (1 - band / 100)
            upper = mid * (1 + band / 100)
            depths[band] = (
                sum(price * quantity for price, quantity in bids if price >= lower),
                sum(price * quantity for price, quantity in asks if price <= upper),
            )
        bid_depth = depths[1.0][0]
        ask_depth = depths[1.0][1]
        total_depth = bid_depth + ask_depth
        imbalance = (
            ((bid_depth - ask_depth) / total_depth) * 100
            if total_depth > 0
            else 0.0
        )
        return {
            "venue": "BINANCE",
            "market_type": "USDT_FUTURES",
            "symbol": str(symbol).upper(),
            "event_time": event_time,
            "last_update_id": str((payload or {}).get("lastUpdateId") or int(event_time.timestamp() * 1000)),
            "best_bid": best_bid,
            "best_ask": best_ask,
            "mid_price": mid,
            "spread_percent": ((best_ask - best_bid) / mid) * 100,
            "bid_depth_05pct": depths[0.5][0],
            "ask_depth_05pct": depths[0.5][1],
            "bid_depth_1pct": bid_depth,
            "ask_depth_1pct": ask_depth,
            "bid_depth_2pct": depths[2.0][0],
            "ask_depth_2pct": depths[2.0][1],
            "imbalance_percent": imbalance,
            "source": "BINANCE_FUTURES_DEPTH",
        }


def _levels(rows):
    levels = []
    for row in rows or []:
        try:
            price = float(row[0])
            quantity = float(row[1])
        except (IndexError, TypeError, ValueError):
            continue
        if price > 0 and quantity >= 0:
            levels.append((price, quantity))
    return levels
