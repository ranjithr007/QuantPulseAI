import sys
import types
from unittest.mock import Mock, patch

fake_requests = types.ModuleType("requests")
fake_requests.get = lambda *args, **kwargs: None
sys.modules.setdefault("requests", fake_requests)

from app.collectors.binances.candle_collector import CandleCollector


def test_binance_candle_collector_parses_result_list_and_sorts_rows():
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "result": {
            "list": [
                ["2000", "2", "3", "1.5", "2.5", "20"],
                ["1000", "1", "2", "0.5", "1.5", "10"],
            ]
        }
    }

    with patch(
        "app.collectors.binances.candle_collector.requests.get",
        return_value=response,
    ):
        candles = CandleCollector().get_candles("BTCUSDT", interval="5m", limit=2)

    assert len(candles) == 2
    assert candles[0]["open_time_ms"] == 1000
    assert candles[0]["open"] == 1.0
    assert candles[0]["close"] == 1.5
    assert candles[1]["open_time_ms"] == 2000
    assert candles[1]["volume"] == 20.0


def test_binance_candle_collector_parses_raw_list_payload():
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = [
        ["1000", "1", "2", "0.5", "1.5", "10"],
        ["2000", "2", "3", "1.5", "2.5", "20"],
    ]

    with patch(
        "app.collectors.binances.candle_collector.requests.get",
        return_value=response,
    ):
        candles = CandleCollector().get_candles("BTCUSDT", interval="5m", limit=2)

    assert len(candles) == 2
    assert candles[0]["open_time_ms"] == 1000
    assert candles[1]["open_time_ms"] == 2000
