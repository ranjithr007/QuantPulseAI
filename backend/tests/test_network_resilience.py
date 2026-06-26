import asyncio
import socket
import sys
import types
from unittest.mock import patch

import pytest

fake_websockets = types.ModuleType("websockets")
fake_websockets.connect = lambda *args, **kwargs: None
sys.modules.setdefault("websockets", fake_websockets)

from app.collectors.binances.candle_collector import CandleCollector
from app.services.live_market_service import LiveMarketService
from app.utils.network_resilience import classify_network_error
from app.utils.network_resilience import is_transient_network_error
from app.utils.network_resilience import summarize_network_error


def test_network_resilience_classifies_common_transient_failures():
    dns_error = socket.gaierror(11001, "Failed to resolve 'api.binance.com'")
    websocket_error = ConnectionResetError(
        10054,
        "An existing connection was forcibly closed by the remote host",
        None,
        10054,
        None,
    )

    assert is_transient_network_error(dns_error)
    assert classify_network_error(dns_error) == "dns resolution failed"
    assert is_transient_network_error(websocket_error)
    assert classify_network_error(websocket_error) == "connection reset by remote host"


def test_network_resilience_summarize_network_error_preserves_business_errors():
    business_error = RuntimeError("boom")

    assert summarize_network_error(business_error) == "boom"


def test_binance_candle_collector_suppresses_transient_network_error_output():
    with patch(
        "app.collectors.binances.candle_collector.requests.get",
        side_effect=ConnectionResetError(
            10054,
            "An existing connection was forcibly closed by the remote host",
            None,
            10054,
            None,
        ),
    ), patch("app.collectors.binances.candle_collector.time.sleep"), patch(
        "builtins.print"
    ) as print_mock:
        candles = CandleCollector().get_candles("BTCUSDT", interval="5m", limit=2)

    assert candles == []
    print_mock.assert_not_called()


def test_binance_candle_collector_suppresses_dns_resolution_failures():
    with patch(
        "app.collectors.binances.candle_collector.requests.get",
        side_effect=socket.gaierror(11001, "Failed to resolve 'api.binance.com'"),
    ), patch("app.collectors.binances.candle_collector.time.sleep"), patch(
        "builtins.print"
    ) as print_mock:
        candles = CandleCollector().get_candles("BTCUSDT", interval="5m", limit=2)

    assert candles == []
    print_mock.assert_not_called()


def test_live_market_service_sanitizes_transient_websocket_errors():
    class _BrokenWebSocket:
        async def __aenter__(self):
            raise ConnectionResetError(
                10054,
                "An existing connection was forcibly closed by the remote host",
                None,
                10054,
                None,
            )

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def _cancel_sleep(_delay):
        raise asyncio.CancelledError

    service = LiveMarketService()

    with patch(
        "app.services.live_market_service.websockets.connect",
        return_value=_BrokenWebSocket(),
    ), patch(
        "app.services.live_market_service.asyncio.sleep",
        new=_cancel_sleep,
    ), patch("builtins.print") as print_mock:
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(service._run(["BTCUSDT"]))

    assert service._last_error == "connection reset by remote host"
    print_mock.assert_not_called()
