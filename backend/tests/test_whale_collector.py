import sys
import types
from unittest.mock import Mock, patch
import socket

fake_requests = types.ModuleType("requests")
fake_requests.get = lambda *args, **kwargs: None
sys.modules.setdefault("requests", fake_requests)

from app.collectors.binances.whale_collector import WhaleCollector
from app.collectors.binances.whale_collector import _retry_delay_seconds


def test_whale_collector_retries_before_succeeding():
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = [
        {"p": "10", "q": "2", "m": False, "T": 1710000000000},
    ]

    with patch(
        "app.collectors.binances.whale_collector.requests.get",
        side_effect=[RuntimeError("boom"), RuntimeError("boom"), response],
    ) as get, patch("app.collectors.binances.whale_collector.time.sleep") as sleep:
        item = WhaleCollector().get_order_flow("BTCUSDT")

    assert item["symbol"] == "BTCUSDT"
    assert get.call_count == 3
    assert sleep.call_count == 2


def test_whale_retry_delay_grows_and_caps():
    assert _retry_delay_seconds(1) == 3
    assert _retry_delay_seconds(2) == 6
    assert _retry_delay_seconds(3) == 12
    assert _retry_delay_seconds(6) == 30


def test_whale_collector_suppresses_dns_resolution_failures():
    with patch(
        "app.collectors.binances.whale_collector.requests.get",
        side_effect=socket.gaierror(11001, "Failed to resolve 'fapi.binance.com'"),
    ), patch("app.collectors.binances.whale_collector.time.sleep"), patch(
        "builtins.print"
    ) as print_mock:
        item = WhaleCollector().get_order_flow("BTCUSDT")

    assert item is None
    print_mock.assert_not_called()
