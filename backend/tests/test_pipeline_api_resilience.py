from unittest.mock import Mock, patch

from app.api.v1.pipeline_api import get_pipeline_performance
from app.api.v1.pipeline_api import get_pipeline_status


def test_pipeline_status_returns_structured_failure_when_watchlist_fails():
    fake_db = Mock()

    with patch("app.api.v1.pipeline_api.SessionLocal", return_value=fake_db), patch(
        "app.api.v1.pipeline_api.build_signal_watchlist_payload",
        side_effect=RuntimeError("boom"),
    ):
        payload = get_pipeline_status()

    assert payload["status"] == "FAILED"
    assert payload["blockers"] == ["Pipeline status unavailable"]
    assert payload["error"] == "boom"
    assert fake_db.rollback.called
    assert fake_db.close.called


def test_pipeline_performance_returns_structured_failure_when_stage_report_fails():
    fake_db = Mock()

    with patch("app.api.v1.pipeline_api.SessionLocal", return_value=fake_db), patch(
        "app.api.v1.pipeline_api.build_signal_watchlist_payload",
        return_value={"timeframes": [], "summary": {"ready": 0, "wait": 0, "long": 0, "short": 0}, "count": 0},
    ), patch(
        "app.api.v1.pipeline_api.TradePlanRepository.get_open_trades",
        side_effect=RuntimeError("boom"),
    ):
        payload = get_pipeline_performance()

    assert payload["source"] == "pipeline_performance_budget"
    assert payload["budget_summary"] == {"stages": 0, "passed": 0, "failed": 0}
    assert payload["error"] == "boom"
    assert fake_db.rollback.called
    assert fake_db.close.called
