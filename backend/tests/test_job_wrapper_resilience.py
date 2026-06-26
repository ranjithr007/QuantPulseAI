from unittest.mock import patch

from app.jobs.paper_trade_execute_job import run_paper_trade_execute_job
from app.jobs.regime_jobs import run_regime_job
from app.jobs.watchlist_persist_job import run_watchlist_persist_job


def test_paper_trade_execute_job_returns_structured_failure():
    with patch(
        "app.jobs.paper_trade_execute_job.execute_paper_trade_candidates_for_symbol",
        side_effect=RuntimeError("boom"),
    ):
        result = run_paper_trade_execute_job()

    assert result["status"] == "FAILED"
    assert result["source"] == "paper_trade_execute"


def test_regime_job_returns_structured_failure():
    with patch(
        "app.jobs.regime_jobs.run_regime_analysis",
        side_effect=RuntimeError("boom"),
    ):
        result = run_regime_job()

    assert result["status"] == "FAILED"
    assert result["source"] == "regime_job"


def test_watchlist_persist_job_returns_structured_failure():
    with patch(
        "app.jobs.watchlist_persist_job.persist_ready_watchlist_setups_for_stack",
        side_effect=RuntimeError("boom"),
    ):
        result = run_watchlist_persist_job()

    assert result["status"] == "FAILED"
    assert result["source"] == "watchlist_persist"
