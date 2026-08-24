import json
import asyncio
import websockets
from hashlib import sha256

from datetime import datetime, timezone

from app.utils.network_resilience import classify_network_error
from app.utils.network_resilience import is_transient_network_error


class LiquidationCollector:

    # Binance retired the legacy /ws futures route in April 2026.  It can
    # complete the WebSocket handshake while silently delivering no frames.
    URL = "wss://fstream.binance.com/market/ws/!forceOrder@arr"

    async def listen(self, callback):
        reconnect_count = 0

        while True:
            try:
                async with websockets.connect(self.URL) as websocket:
                    reconnect_count = 0
                    print("Liquidation stream connected")

                    while True:
                        message = await websocket.recv()

                        liquidation = _parse_liquidation_message(message)
                        if liquidation is None:
                            continue

                        result = callback(liquidation)
                        if asyncio.iscoroutine(result):
                            await result
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                reconnect_count += 1
                delay = _reconnect_delay_seconds(reconnect_count)
                if not is_transient_network_error(exc):
                    print(
                        f"Liquidation stream error: {classify_network_error(exc)} "
                        f"(retrying in {delay}s)"
                    )
                await asyncio.sleep(delay)


def _parse_liquidation_message(message):
    try:
        data = json.loads(message)
        if isinstance(data, dict) and "data" in data:
            data = data["data"]
        order = data["o"]
        event_time = data.get("E")
        if event_time is None:
            return None

        average_price = float(order.get("ap") or 0)
        accumulated_quantity = float(order.get("z") or 0)
        price = average_price if average_price > 0 else float(order["p"])
        quantity = (
            accumulated_quantity
            if accumulated_quantity > 0
            else float(order["q"])
        )
        event_identity = "|".join(
            str(item)
            for item in (
                order["s"],
                order["S"],
                event_time,
                order.get("T"),
                price,
                quantity,
            )
        )

        return {
            "venue": "BINANCE",
            "exchange_event_id": sha256(event_identity.encode("utf-8")).hexdigest()[:40],
            "symbol": order["s"],
            "side": order["S"],
            "price": price,
            "quantity": quantity,
            "value_usd": price * quantity,
            "event_time": datetime.fromtimestamp(
                int(event_time) / 1000,
                tz=timezone.utc,
            ),
        }
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _reconnect_delay_seconds(reconnect_count):
    return min(60, 5 * (2 ** min(max(reconnect_count - 1, 0), 4)))
