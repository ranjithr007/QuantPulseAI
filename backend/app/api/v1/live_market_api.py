from fastapi import APIRouter
from fastapi import Query
from fastapi import WebSocket
from fastapi import WebSocketDisconnect

from app.services.live_market_service import get_live_market_service
from app.services.live_market_service import start_live_market_listener


router = APIRouter(tags=["Live Market"])


@router.get("/live/market-snapshot")
async def get_live_market_snapshot(symbols: str | None = Query(default=None)):
    service = get_live_market_service()
    records = service.snapshot(symbols)

    return {
        "source": "live_market_cache",
        "count": len(records),
        "records": records,
    }


@router.get("/live/status")
async def get_live_market_status():
    service = get_live_market_service()
    return {
        "source": "live_market_cache",
        **service.status(),
    }


@router.post("/live/start")
async def start_live_market(symbols: str | None = Query(default=None)):
    started = start_live_market_listener(symbols)
    service = get_live_market_service()

    return {
        "source": "live_market_cache",
        "started": started,
        **service.status(),
    }


@router.websocket("/ws/live-market")
async def live_market_websocket(websocket: WebSocket, symbols: str | None = None):
    service = get_live_market_service()
    await websocket.accept()

    queue = service.subscribe()

    try:
        await websocket.send_json(
            {
                "type": "snapshot",
                "source": "live_market_cache",
                "records": service.snapshot(symbols),
            }
        )

        selected_symbols = _parse_symbols(symbols)

        while True:
            record = await queue.get()

            if selected_symbols and record["symbol"] not in selected_symbols:
                continue

            await websocket.send_json(
                {
                    "type": "live_market",
                    "source": "binance_ws_kline",
                    "record": record,
                }
            )

    except WebSocketDisconnect:
        pass
    finally:
        service.unsubscribe(queue)


def _parse_symbols(symbols):
    if not symbols:
        return None

    return {item.strip().upper() for item in symbols.split(",") if item.strip()}
