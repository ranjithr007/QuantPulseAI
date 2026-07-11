from fastapi import APIRouter
from fastapi import Query
from fastapi import WebSocket
from fastapi import WebSocketDisconnect

from app.services.live_market_service import get_live_market_service
from app.services.live_market_service import start_live_market_listener
from app.utils.network_resilience import summarize_network_error


router = APIRouter(tags=["Live Market"])


@router.get("/live/market-snapshot")
async def get_live_market_snapshot(symbols: str | None = Query(default=None)):
    service = get_live_market_service()

    try:
        records = service.snapshot(symbols)
        return {
            "source": "live_market_cache",
            "count": len(records),
            "records": records,
        }
    except Exception as exc:
        return _live_market_error_payload("snapshot", exc, symbols=symbols)


@router.get("/live/status")
async def get_live_market_status():
    service = get_live_market_service()

    try:
        return {
            "source": "live_market_cache",
            **service.status(),
        }
    except Exception as exc:
        return _live_market_error_payload("status", exc)


@router.post("/live/start")
async def start_live_market(symbols: str | None = Query(default=None)):
    service = get_live_market_service()

    try:
        started = start_live_market_listener(symbols)
        return {
            "source": "live_market_cache",
            "started": started,
            **service.status(),
        }
    except Exception as exc:
        return _live_market_error_payload("start", exc, symbols=symbols)


@router.websocket("/ws/live-market")
async def live_market_websocket(websocket: WebSocket, symbols: str | None = None):
    service = get_live_market_service()
    start_live_market_listener(symbols)
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
    except Exception:
        await websocket.close(code=1011)
    finally:
        service.unsubscribe(queue)


def _parse_symbols(symbols):
    if not symbols:
        return None

    return {item.strip().upper() for item in symbols.split(",") if item.strip()}


def _live_market_error_payload(operation, exc, symbols=None):
    payload = {
        "source": "live_market_cache",
        "available": False,
        "operation": operation,
        "status": "FAILED",
        "error": summarize_network_error(exc),
    }

    if symbols is not None:
        payload["symbols"] = symbols

    return payload
