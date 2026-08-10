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
    assert candles[0]["close_time_ms"] == 301000
    assert candles[0]["venue"] == "BYBIT"
    assert candles[0]["market_type"] == "FUTURES"
    assert candles[0]["source"] == "BYBIT_FUTURES_REST"
    assert candles[0]["is_final"] is True
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


def test_bybit_incremental_request_maps_hour_interval_and_boundaries():
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "retCode": 0,
        "result": {
            "list": [
                ["3600000", "1", "2", "0.5", "1.5", "10"],
            ]
        },
    }

    with patch(
        "app.collectors.Bybit.candle_collector.requests.get",
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
    assert params["category"] == "linear"
    assert params["interval"] == "60"
    assert params["start"] == 3_600_000
    assert params["end"] == 7_200_000


def test_bybit_list_turnover_field_is_not_treated_as_close_timestamp():
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "retCode": 0,
        "result": {
            "list": [
                [
                    "3600000",
                    "1",
                    "2",
                    "0.5",
                    "1.5",
                    "10",
                    "15.25",
                ],
            ]
        },
    }

    with patch(
        "app.collectors.Bybit.candle_collector.requests.get",
        return_value=response,
    ):
        candles = CandleCollector().get_candles(
            "BTCUSDT",
            interval="1h",
            limit=1,
        )

    assert len(candles) == 1
    assert candles[0]["open_time_ms"] == 3_600_000
    assert candles[0]["close_time_ms"] == 7_200_000
