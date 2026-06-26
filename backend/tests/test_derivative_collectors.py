import sys
import types
from types import SimpleNamespace
from unittest.mock import Mock, patch
import socket

fake_requests = types.ModuleType("requests")
fake_requests.get = lambda *args, **kwargs: None
sys.modules.setdefault("requests", fake_requests)

from app.collectors.binances.funding_collector import FundingCollector
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
        "app.jobs.derivative_job.DerivativeRepository.save_funding"
    ) as save_funding, patch(
        "app.jobs.derivative_job.DerivativeRepository.save_open_interest"
    ) as save_open_interest:
        run_derivative_job()

    assert not save_funding.called
    assert save_open_interest.called
    assert fake_db.close.called
