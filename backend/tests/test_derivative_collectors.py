import sys
import types
from types import SimpleNamespace
from unittest.mock import Mock, patch
import socket

fake_requests = types.ModuleType("requests")
fake_requests.get = lambda *args, **kwargs: None
sys.modules.setdefault("requests", fake_requests)

from app.collectors.binances.funding_collector import FundingCollector
from app.collectors.binances.mark_price_collector import MarkPriceCollector
from app.collectors.binances.leverage_bracket_collector import LeverageBracketCollector
from app.collectors.binances.open_interest_collector import OpenInterestCollector
from app.jobs.derivative_job import run_derivative_job


def test_funding_collector_parses_latest_row():
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = [
        {"fundingRate": "0.0005", "fundingTime": 1710000000000},
    ]

    with patch(
        "app.collectors.binances.funding_collector.requests.get",
        return_value=response,
    ):
        item = FundingCollector().get_funding("BTCUSDT")

    assert item["symbol"] == "BTCUSDT"
    assert item["rate"] == 0.0005
    assert item["time"].year == 2024


def test_funding_collector_retries_before_succeeding():
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = [
        {"fundingRate": "0.0010", "fundingTime": 1710000000000},
    ]

    with patch(
        "app.collectors.binances.funding_collector.requests.get",
        side_effect=[RuntimeError("boom"), RuntimeError("boom"), response],
    ) as get, patch("app.collectors.binances.funding_collector.time.sleep") as sleep:
        item = FundingCollector().get_funding("BTCUSDT")

    assert item["rate"] == 0.001
    assert get.call_count == 3
    assert sleep.call_count == 2


def test_open_interest_collector_parses_payload_and_uses_current_time():
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"openInterest": "123.45"}

    with patch(
        "app.collectors.binances.open_interest_collector.requests.get",
        return_value=response,
    ):
        item = OpenInterestCollector().get_data("BTCUSDT")

    assert item["symbol"] == "BTCUSDT"
    assert item["value"] == 123.45
    assert item["time"].year >= 2024


def test_open_interest_collector_parses_top_level_list_payload():
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = [
        {"openInterest": "234.56"},
    ]

    with patch(
        "app.collectors.binances.open_interest_collector.requests.get",
        return_value=response,
    ):
        item = OpenInterestCollector().get_data("BTCUSDT")

    assert item["symbol"] == "BTCUSDT"
    assert item["value"] == 234.56


def test_open_interest_collector_retries_before_succeeding():
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"openInterest": "456.78"}

    with patch(
        "app.collectors.binances.open_interest_collector.requests.get",
        side_effect=[RuntimeError("boom"), RuntimeError("boom"), response],
    ) as get, patch("app.collectors.binances.open_interest_collector.time.sleep") as sleep:
        item = OpenInterestCollector().get_data("BTCUSDT")

    assert item["value"] == 456.78
    assert get.call_count == 3
    assert sleep.call_count == 2


def test_funding_collector_suppresses_dns_resolution_failures():
    with patch(
        "app.collectors.binances.funding_collector.requests.get",
        side_effect=socket.gaierror(11001, "Failed to resolve 'fapi.binance.com'"),
    ), patch("app.collectors.binances.funding_collector.time.sleep"), patch(
        "builtins.print"
    ) as print_mock:
        item = FundingCollector().get_funding("BTCUSDT")

    assert item is None
    print_mock.assert_not_called()


def test_open_interest_collector_suppresses_dns_resolution_failures():
    with patch(
        "app.collectors.binances.open_interest_collector.requests.get",
        side_effect=socket.gaierror(11001, "Failed to resolve 'fapi.binance.com'"),
    ), patch("app.collectors.binances.open_interest_collector.time.sleep"), patch(
        "builtins.print"
    ) as print_mock:
        item = OpenInterestCollector().get_data("BTCUSDT")

    assert item is None
    print_mock.assert_not_called()


def test_mark_price_collector_parses_only_final_klines():
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = [
        [1710000000000, "100", "105", "95", "102", "0", 1710003599999],
        [9999999999000, "102", "106", "101", "104", "0", 9999999999999],
    ]

    with patch(
        "app.collectors.binances.mark_price_collector.requests.get",
        return_value=response,
    ):
        rows = MarkPriceCollector().get_klines("BTCUSDT", "1h")

    assert len(rows) == 1
    assert rows[0]["symbol"] == "BTCUSDT"
    assert rows[0]["timeframe"] == "1h"
    assert rows[0]["high_price"] == 105
    assert rows[0]["is_final"] is True


def test_mark_price_collector_fetches_current_mark_for_deadline_exit():
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "symbol": "XRPUSDT",
        "markPrice": "1.0025",
        "time": 1786977000000,
    }

    with patch(
        "app.collectors.binances.mark_price_collector.requests.get",
        return_value=response,
    ):
        item = MarkPriceCollector().get_current_mark_price("XRPUSDT")

    assert item["symbol"] == "XRPUSDT"
    assert item["mark_price"] == 1.0025
    assert item["source"] == "BINANCE_FUTURES_MARK_PRICE"


def test_leverage_bracket_collector_fails_closed_without_credentials():
    collector = LeverageBracketCollector(api_key="", api_secret="")
    collector.api_key = None
    collector.api_secret = None

    assert collector.get_brackets("BTCUSDT") == []
    assert collector.last_status == "CREDENTIALS_UNAVAILABLE"


def test_leverage_bracket_collector_versions_normalized_snapshot():
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "symbol": "DOGEUSDT",
        "brackets": [
            {
                "bracket": 1,
                "initialLeverage": 75,
                "notionalCap": 10000,
                "notionalFloor": 0,
                "maintMarginRatio": 0.0065,
                "cum": 0,
            }
        ],
    }

    with patch(
        "app.collectors.binances.leverage_bracket_collector.requests.get",
        return_value=response,
    ):
        rows = LeverageBracketCollector("key", "secret").get_brackets("DOGEUSDT")

    assert len(rows) == 1
    assert rows[0]["bracket_number"] == 1
    assert rows[0]["maintenance_margin_rate"] == 0.0065
    assert len(rows[0]["snapshot_version"]) == 64


def test_derivative_job_skips_missing_collector_payloads():
    fake_db = SimpleNamespace(close=Mock())
    fake_symbol = SimpleNamespace(symbol="BTCUSDT")

    with patch("app.jobs.derivative_job.SessionLocal", return_value=fake_db), patch(
        "app.jobs.derivative_job.SymbolRepository.get_active_symbols",
        return_value=[fake_symbol],
    ), patch(
        "app.jobs.derivative_job.FundingCollector.get_funding",
        return_value=None,
    ), patch(
        "app.jobs.derivative_job.OpenInterestCollector.get_data",
        return_value={"symbol": "BTCUSDT", "value": 1.0, "time": object()},
    ), patch(
        "app.jobs.derivative_job.MarkPriceCollector.get_klines",
        return_value=[],
    ) as get_mark_prices, patch(
        "app.jobs.derivative_job.LeverageBracketCollector.get_brackets",
        return_value=[],
    ), patch(
        "app.jobs.derivative_job.DerivativeRepository.save_funding"
    ) as save_funding, patch(
        "app.jobs.derivative_job.DerivativeRepository.save_open_interest"
    ) as save_open_interest:
        run_derivative_job()

    assert not save_funding.called
    assert save_open_interest.called
    assert [call.args[1] for call in get_mark_prices.call_args_list] == [
        "5m",
        "1h",
        "2h",
        "4h",
        "1d",
    ]
    assert fake_db.close.called
