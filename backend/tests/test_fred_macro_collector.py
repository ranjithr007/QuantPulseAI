from datetime import datetime, timezone
from unittest.mock import Mock, patch

from app.collectors.fred_macro_collector import FredMacroCollector
from app.collectors.fred_macro_collector import SERIES_SPECS


LATEST_VALUES = {
    "DGS2": 4.0,
    "DGS10": 4.2,
    "DTWEXBGS": 100.0,
    "WALCL": 7_100.0,
    "RRPONTSYD": 100.0,
    "WTREGEN": 700.0,
    "DFF": 4.0,
    "VIXCLS": 15.0,
}

PREVIOUS_VALUES = {
    "DGS2": 4.1,
    "DGS10": 4.25,
    "DTWEXBGS": 101.0,
    "WALCL": 7_000.0,
    "RRPONTSYD": 120.0,
    "WTREGEN": 750.0,
    "DFF": 4.1,
    "VIXCLS": 16.0,
}


def _response(series_id):
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "observations": [
            {"date": "2026-08-21", "value": str(LATEST_VALUES[series_id])},
            {"date": "2026-08-20", "value": str(PREVIOUS_VALUES[series_id])},
        ]
    }
    return response


def test_missing_fred_key_is_explicitly_unavailable_without_network_call():
    FredMacroCollector.clear_cache()
    with patch("app.collectors.fred_macro_collector.requests.get") as request:
        result = FredMacroCollector("").collect(
            now=datetime(2026, 8, 22, tzinfo=timezone.utc)
        )

    assert result["status"] == "NOT_CONFIGURED"
    assert result["macro_score"] is None
    assert result["advisory_only"] is True
    request.assert_not_called()


def test_fresh_core_fred_series_produce_verified_supportive_macro_score_and_cache():
    FredMacroCollector.clear_cache()

    def fake_get(_url, *, params, timeout):
        assert timeout == 7
        assert params["api_key"] == "test-key"
        return _response(params["series_id"])

    collector = FredMacroCollector("test-key", timeout_seconds=7, cache_seconds=1800)
    with patch(
        "app.collectors.fred_macro_collector.requests.get",
        side_effect=fake_get,
    ) as request:
        first = collector.collect(
            force_refresh=True,
            now=datetime(2026, 8, 22, tzinfo=timezone.utc),
        )
        second = collector.collect(now=datetime(2026, 8, 22, tzinfo=timezone.utc))

    assert first["status"] == "VERIFIED"
    assert first["provider"] == "FRED"
    assert first["series_count"] == len(SERIES_SPECS)
    assert first["macro_score"] > 0
    assert "US 2-year Treasury yield is falling" in first["reasons"]
    assert first["series"]["DTWEXBGS"]["contribution"] > 0
    assert second == first
    assert request.call_count == len(SERIES_SPECS)


def test_rising_yields_dollar_and_volatility_produce_verified_restrictive_score():
    FredMacroCollector.clear_cache()
    restrictive_latest = {
        "DGS2": 4.2,
        "DGS10": 4.35,
        "DTWEXBGS": 102.0,
        "WALCL": 6_900.0,
        "RRPONTSYD": 140.0,
        "WTREGEN": 800.0,
        "DFF": 4.2,
        "VIXCLS": 18.0,
    }

    def fake_get(_url, *, params, timeout):
        series_id = params["series_id"]
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "observations": [
                {"date": "2026-08-21", "value": str(restrictive_latest[series_id])},
                {"date": "2026-08-20", "value": str(LATEST_VALUES[series_id])},
            ]
        }
        return response

    with patch(
        "app.collectors.fred_macro_collector.requests.get",
        side_effect=fake_get,
    ):
        result = FredMacroCollector("test-key").collect(
            force_refresh=True,
            now=datetime(2026, 8, 22, tzinfo=timezone.utc),
        )

    assert result["status"] == "VERIFIED"
    assert result["macro_score"] < 0
    assert "Broad US dollar index is strengthening" in result["reasons"]
    assert result["series"]["VIXCLS"]["contribution"] < 0


def test_missing_core_fred_series_cannot_be_marked_verified():
    FredMacroCollector.clear_cache()

    def fake_get(_url, *, params, timeout):
        if params["series_id"] == "DGS2":
            raise TimeoutError("timed out")
        return _response(params["series_id"])

    with patch(
        "app.collectors.fred_macro_collector.requests.get",
        side_effect=fake_get,
    ):
        result = FredMacroCollector("test-key").collect(
            force_refresh=True,
            now=datetime(2026, 8, 22, tzinfo=timezone.utc),
        )

    assert result["status"] == "DEGRADED"
    assert result["errors"]["DGS2"] == "TimeoutError"
    assert result["advisory_only"] is True


def test_dollar_index_allows_one_publication_weekend_but_not_two():
    FredMacroCollector.clear_cache()

    def fake_get(_url, *, params, timeout):
        series_id = params["series_id"]
        response = Mock()
        response.raise_for_status.return_value = None
        latest_date = "2026-08-14" if series_id == "DTWEXBGS" else "2026-08-20"
        previous_date = "2026-08-13" if series_id == "DTWEXBGS" else "2026-08-19"
        response.json.return_value = {
            "observations": [
                {"date": latest_date, "value": str(LATEST_VALUES[series_id])},
                {"date": previous_date, "value": str(PREVIOUS_VALUES[series_id])},
            ]
        }
        return response

    collector = FredMacroCollector("test-key", cache_seconds=0)
    with patch(
        "app.collectors.fred_macro_collector.requests.get",
        side_effect=fake_get,
    ):
        weekend = collector.collect(
            force_refresh=True,
            now=datetime(2026, 8, 22, tzinfo=timezone.utc),
        )
        missed_cycle = collector.collect(
            force_refresh=True,
            now=datetime(2026, 8, 25, tzinfo=timezone.utc),
        )

    assert weekend["status"] == "VERIFIED"
    assert weekend["series"]["DTWEXBGS"]["age_days"] == 8
    assert weekend["series"]["DTWEXBGS"]["is_stale"] is False
    assert missed_cycle["status"] == "DEGRADED"
    assert missed_cycle["series"]["DTWEXBGS"]["age_days"] == 11
    assert missed_cycle["series"]["DTWEXBGS"]["is_stale"] is True


def test_fred_cache_is_bounded_when_credentials_rotate():
    FredMacroCollector.clear_cache()
    collector = FredMacroCollector("test-key")

    for index in range(FredMacroCollector._cache_max_entries + 2):
        collector._store_cache(f"key-{index}", {"index": index})

    assert len(FredMacroCollector._cache) == FredMacroCollector._cache_max_entries
    assert "key-0" not in FredMacroCollector._cache
    assert "key-1" not in FredMacroCollector._cache
