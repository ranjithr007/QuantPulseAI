import asyncio
import sys
import types
from unittest.mock import patch

fake_websockets = types.ModuleType("websockets")
fake_websockets.connect = lambda *args, **kwargs: None
sys.modules.setdefault("websockets", fake_websockets)

from fastapi.responses import JSONResponse
from starlette.requests import Request

from app.main import ensure_cors_headers


def test_ensure_cors_headers_returns_500_and_preserves_allowed_origin_header():
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(b"origin", b"http://localhost:4173")],
    }

    async def receive():
        return {"type": "http.request"}

    request = Request(scope, receive)

    async def call_next(_request):
        raise RuntimeError("boom")

    with patch("app.main.print") as printed:
        response = asyncio.run(ensure_cors_headers(request, call_next))

    assert response.status_code == 500
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:4173"
    assert response.headers["Access-Control-Allow-Credentials"] == "true"
    assert response.headers["Vary"] == "Origin"
    assert printed.called


def test_ensure_cors_headers_does_not_add_cors_for_unapproved_origin():
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(b"origin", b"http://evil.example")],
    }

    async def receive():
        return {"type": "http.request"}

    request = Request(scope, receive)

    async def call_next(_request):
        return JSONResponse({"ok": True})

    response = asyncio.run(ensure_cors_headers(request, call_next))

    assert response.headers.get("Access-Control-Allow-Origin") is None
    assert response.status_code == 200
