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
    assert candles[0]["close_time_ms"] == 301000
    assert candles[0]["venue"] == "BINANCE"
    assert candles[0]["market_type"] == "FUTURES"
    assert candles[0]["source"] == "BINANCE_FUTURES_REST"
    assert candles[0]["is_final"] is True
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


def test_binance_incremental_request_uses_start_and_end_boundaries():
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = [
        ["3600000", "1", "2", "0.5", "1.5", "10"],
    ]

    with patch(
        "app.collectors.binances.candle_collector.requests.get",
        return_value=response,
    ) as request_get:
        CandleCollector().get_candles(
            "BTCUSDT",
            interval="1h",
            limit=1,
            start_time_ms=3_600_000,
            end_time_ms=7_200_000,
        )

    params = request_get.call_args.kwargs["params"]
    assert params["startTime"] == 3_600_000
    assert params["endTime"] == 7_200_000
    assert params["limit"] == 1
