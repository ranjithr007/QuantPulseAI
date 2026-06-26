import asyncio
import sys
import types
from unittest.mock import Mock, patch

fake_websockets = types.ModuleType("websockets")
fake_websockets.connect = lambda *args, **kwargs: None
sys.modules.setdefault("websockets", fake_websockets)

from app.api.v1.live_market_api import get_live_market_snapshot
from app.api.v1.live_market_api import get_live_market_status
from app.api.v1.live_market_api import start_live_market


def test_live_market_snapshot_returns_structured_failure_on_error():
    service = Mock()
    service.snapshot.side_effect = RuntimeError("boom")

    with patch("app.api.v1.live_market_api.get_live_market_service", return_value=service):
        payload = asyncio.run(get_live_market_snapshot("BTCUSDT"))

    assert payload["status"] == "FAILED"
    assert payload["operation"] == "snapshot"
    assert payload["symbols"] == "BTCUSDT"
    assert payload["error"] == "boom"


def test_live_market_status_returns_structured_failure_on_error():
    service = Mock()
    service.status.side_effect = RuntimeError("boom")

    with patch("app.api.v1.live_market_api.get_live_market_service", return_value=service):
        payload = asyncio.run(get_live_market_status())

    assert payload["status"] == "FAILED"
    assert payload["operation"] == "status"
    assert payload["error"] == "boom"


def test_live_market_start_returns_structured_failure_on_error():
    service = Mock()
    service.status.return_value = {"running": False}

    with patch("app.api.v1.live_market_api.get_live_market_service", return_value=service), patch(
        "app.api.v1.live_market_api.start_live_market_listener",
        side_effect=RuntimeError("boom"),
    ):
        payload = asyncio.run(start_live_market("BTCUSDT"))

    assert payload["status"] == "FAILED"
    assert payload["operation"] == "start"
    assert payload["symbols"] == "BTCUSDT"
    assert payload["error"] == "boom"
