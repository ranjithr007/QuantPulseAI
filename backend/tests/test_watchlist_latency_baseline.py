from unittest.mock import Mock, patch

from app.api.v1.signals_api import get_watchlist_latency_baseline


def test_watchlist_latency_baseline_invokes_watchlist_stage_and_returns_stage_report():
    fake_db = Mock()
    fake_db.close = Mock()
    calls = []

    def fake_stage_report(stage_operations, sample_size=5, budgets=None):
        calls.append(sample_size)
        watchlist_payload = stage_operations["watchlist"]()
        return {
            "sample_size": sample_size,
            "stages": {
                "watchlist": {
                    "sample_count": sample_size,
                    "budget_passed": True,
                    "payload": watchlist_payload,
                }
            },
        }

    with patch("app.api.v1.signals_api.SessionLocal", return_value=fake_db), patch(
        "app.api.v1.signals_api.build_signal_watchlist_payload",
        return_value={"source": "signal_watchlist", "count": 3, "timeframes": ["5m", "15m", "1h"], "summary": {"ready": 0, "wait": 0, "long": 0, "short": 0}, "records": [], "cache": {"hit": True, "age_seconds": 0, "ttl_seconds": 15}, "filters": {"status": None, "side": None, "failed_max": None}, "sort": "priority", "total_count": 3},
    ), patch(
        "app.api.v1.signals_api.build_stage_latency_report",
        side_effect=fake_stage_report,
    ):
        payload = get_watchlist_latency_baseline(mode="intraday", sample_size=3)

    assert calls == [3]
    assert payload["source"] == "watchlist_latency_baseline"
    assert payload["stage"]["budget_passed"] is True
    assert payload["stage"]["payload"]["count"] == 3
    assert fake_db.close.called
