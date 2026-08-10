import asyncio
import sys
import types
from types import SimpleNamespace
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

    with patch("app.main.http_logger") as logger:
        response = asyncio.run(ensure_cors_headers(request, call_next))

    assert response.status_code == 500
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:4173"
    assert response.headers["Access-Control-Allow-Credentials"] == "true"
    assert response.headers["Vary"] == "Origin"
    assert logger.exception.called
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers.get("X-Request-ID")


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


def test_mutating_request_requires_admin_auth_when_enabled():
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/scheduler/start",
        "headers": [(b"origin", b"http://localhost:4173")],
    }

    async def receive():
        return {"type": "http.request"}

    request = Request(scope, receive)

    async def call_next(_request):
        return JSONResponse({"unexpected": True})

    auth_settings = SimpleNamespace(
        require_admin_auth=True,
        admin_api_key="a" * 32,
    )
    with patch("app.main.settings", auth_settings):
        response = asyncio.run(ensure_cors_headers(request, call_next))

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_mutating_request_accepts_valid_bearer_admin_key():
    admin_key = "b" * 32
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/paper-trade/execute-candidates",
        "headers": [(b"authorization", f"Bearer {admin_key}".encode())],
    }

    async def receive():
        return {"type": "http.request"}

    request = Request(scope, receive)

    async def call_next(_request):
        return JSONResponse({"ok": True})

    auth_settings = SimpleNamespace(
        require_admin_auth=True,
        admin_api_key=admin_key,
    )
    with patch("app.main.settings", auth_settings):
        response = asyncio.run(ensure_cors_headers(request, call_next))

    assert response.status_code == 200


def test_rate_limited_request_returns_429():
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/signals/watchlist",
        "headers": [],
        "client": ("203.0.113.10", 12345),
    }

    async def receive():
        return {"type": "http.request"}

    request = Request(scope, receive)

    async def call_next(_request):
        return JSONResponse({"unexpected": True})

    rate_settings = SimpleNamespace(
        require_admin_auth=False,
        rate_limit_enabled=True,
        rate_limit_per_minute=1,
        admin_rate_limit_per_minute=1,
        trust_proxy_headers=False,
        environment="production",
    )
    limiter = SimpleNamespace(allow=lambda *_args, **_kwargs: False)
    with (
        patch("app.main.settings", rate_settings),
        patch("app.main.rate_limiter", limiter),
    ):
        response = asyncio.run(ensure_cors_headers(request, call_next))

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "60"
    assert "max-age=31536000" in response.headers["Strict-Transport-Security"]
