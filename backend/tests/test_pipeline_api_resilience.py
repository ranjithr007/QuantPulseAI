from collections import Counter
from unittest.mock import Mock, patch

from app.api.v1.pipeline_api import _paper_candidate_stage
from app.api.v1.pipeline_api import _pipeline_blockers
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


def test_pipeline_candidate_stage_distinguishes_trade_eligibility_from_executor_readiness():
    stage = _paper_candidate_stage(
        [{"eligible": True}, {"eligible": False}],
        [{"eligible": True}],
        [],
        Counter({"Strategy failed expectancy": 1}),
        Counter({"Portfolio drawdown limit reached": 1}),
    )

    assert stage["eligible_count"] == 1
    assert stage["has_eligible"] is True
    assert stage["executor_ready_count"] == 0
    assert stage["has_executor_ready"] is False
    assert stage["candidate_blockers"] == {"Strategy failed expectancy": 1}
    assert stage["global_execution_blockers"] == {
        "Portfolio drawdown limit reached": 1
    }


def test_pipeline_blockers_report_global_safety_reason_when_candidates_cannot_execute():
    blockers = _pipeline_blockers(
        {
            "watchlist": {"has_ready": True},
            "trade_plans": {"has_open": True},
            "risk": {"has_decisions": True},
            "paper_candidates": {
                "has_eligible": True,
                "has_executor_ready": False,
                "global_execution_blockers": {
                    "Portfolio drawdown limit reached": 1
                },
            },
            "paper_trades": {"has_open": False},
        }
    )

    assert blockers == [
        "Portfolio drawdown limit reached",
        "No OPEN paper trades",
    ]
