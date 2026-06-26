import sys
import types
from unittest.mock import Mock, patch

fake_requests = types.ModuleType("requests")
fake_requests.get = lambda *args, **kwargs: None
sys.modules.setdefault("requests", fake_requests)

from app.collectors.Bybit.candle_collector import CandleCollector
from app.collectors.Bybit.candle_collector import _retry_delay_seconds


def test_bybit_candle_collector_parses_result_list_and_sorts_rows():
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "retCode": 0,
        "result": {
            "list": [
                ["2000", "2", "3", "1.5", "2.5", "20"],
                ["1000", "1", "2", "0.5", "1.5", "10"],
            ]
        },
    }

    with patch(
        "app.collectors.Bybit.candle_collector.requests.get",
        return_value=response,
    ):
        candles = CandleCollector().get_candles("BTCUSDT", interval="5m", limit=2)

    assert len(candles) == 2
    assert candles[0]["open_time_ms"] == 1000
    assert candles[0]["open"] == 1.0
    assert candles[0]["close"] == 1.5
    assert candles[1]["open_time_ms"] == 2000
    assert candles[1]["volume"] == 20.0


def test_bybit_candle_collector_parses_top_level_list_payload():
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = [
        ["2000", "2", "3", "1.5", "2.5", "20"],
        ["1000", "1", "2", "0.5", "1.5", "10"],
    ]

    with patch(
        "app.collectors.Bybit.candle_collector.requests.get",
        return_value=response,
    ):
        candles = CandleCollector().get_candles("BTCUSDT", interval="5m", limit=2)

    assert len(candles) == 2
    assert candles[0]["open_time_ms"] == 1000
    assert candles[1]["open_time_ms"] == 2000


def test_bybit_candle_retry_delay_grows_and_caps():
    assert _retry_delay_seconds(1) == 3
    assert _retry_delay_seconds(2) == 6
    assert _retry_delay_seconds(3) == 12
    assert _retry_delay_seconds(6) == 30


def test_bybit_candle_collector_suppresses_dns_resolution_failures():
    with patch(
        "app.collectors.Bybit.candle_collector.requests.get",
        side_effect=OSError(11001, "Failed to resolve 'api.bybit.com'"),
    ), patch("app.collectors.Bybit.candle_collector.time.sleep"), patch(
        "builtins.print"
    ) as print_mock:
        candles = CandleCollector().get_candles("BTCUSDT", interval="5m", limit=2)

    assert candles == []
    print_mock.assert_not_called()
