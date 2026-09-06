"""Read-only connectivity probe. Does not open a DB or execute paper/live trades."""
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import websockets
from app.services.paper_exit_prices import PaperExitPrices, STREAM_URL


async def check():
    cache = PaperExitPrices()
    async with websockets.connect(STREAM_URL, open_timeout=8, close_timeout=1) as socket:
        timings = []
        events = []
        while len(events) < 3:
            payload = json.loads(await asyncio.wait_for(socket.recv(), timeout=8))
            cache.ingest(payload)
            for row in payload:
                if row.get("s") == "BTCUSDT" and (not events or row["E"] > events[-1]):
                    events.append(row["E"])
                    timings.append(time.monotonic())
        fresh_btc = cache.take(["BTCUSDT"])["BTCUSDT"]
        result = {
            "stream_connected": True,
            "fresh_btc_marks": len(fresh_btc),
            "frame_intervals_seconds": [round(b - a, 3) for a, b in zip(timings, timings[1:])],
            "orders_sent": 0,
        }
        print(json.dumps(result))
        return 0 if fresh_btc else 1


if __name__ == "__main__":
    try:
        async def bounded_check():
            return await asyncio.wait_for(check(), timeout=15)
        sys.exit(asyncio.run(bounded_check()))
    except Exception as exc:
        print(json.dumps({"stream_connected": False, "error_type": type(exc).__name__, "orders_sent": 0}))
        sys.exit(1)
