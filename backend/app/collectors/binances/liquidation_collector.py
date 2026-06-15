import json
import asyncio
import websockets

from datetime import datetime


class LiquidationCollector:

    URL = "wss://fstream.binance.com" "/ws/!forceOrder@arr"

    async def listen(self, callback):

        async with websockets.connect(self.URL) as websocket:

            print("Liquidation stream connected")

            while True:

                message = await websocket.recv()

                data = json.loads(message)

                order = data["o"]

                liquidation = {
                    "symbol": order["s"],
                    "side": order["S"],
                    "price": float(order["p"]),
                    "quantity": float(order["q"]),
                    "value_usd": float(order["p"]) * float(order["q"]),
                    "event_time": datetime.fromtimestamp(data["E"] / 1000),
                }

                callback(liquidation)