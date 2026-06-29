import importlib
import sys
from unittest.mock import Mock, patch

import pytest
from unittest.mock import Mock

from app.jobs.feature_jobs import run_feature_job
from app.jobs.ml_dataset_job import run_ml_dataset_job
from app.jobs.paper_trade_monitor_job import run_paper_trade_monitor_job
from app.jobs.risk_job import run_risk_job, RiskJob


def test_feature_job_rolls_back_and_closes_on_symbol_fetch_error():
    fake_db = Mock()

    with patch("app.jobs.feature_jobs.SessionLocal", return_value=fake_db), patch(
        "app.jobs.feature_jobs.SymbolRepository.get_active_symbols",
        side_effect=RuntimeError("boom"),
    ):
        results = run_feature_job()

    assert fake_db.rollback.called
    assert fake_db.close.called


def test_ml_dataset_job_rolls_back_and_closes_on_symbol_fetch_error():
    fake_db = Mock()

    with patch("app.jobs.ml_dataset_job.SessionLocal", return_value=fake_db), patch(
        "app.jobs.ml_dataset_job.SymbolRepository.get_active_symbols",
        side_effect=RuntimeError("boom"),
    ):
        run_ml_dataset_job()

    assert fake_db.rollback.called
    assert fake_db.close.called


def test_paper_trade_monitor_job_rolls_back_and_closes_on_open_trade_error():
    fake_db = Mock()

    with patch(
        "app.jobs.paper_trade_monitor_job.SessionLocal", return_value=fake_db
    ), patch(
        "app.jobs.paper_trade_monitor_job.PaperTradeRepository.get_open_trades",
        side_effect=RuntimeError("boom"),
    ):
        result = run_paper_trade_monitor_job()

    assert fake_db.rollback.called
    assert fake_db.close.called
    assert result["errors"]


def test_risk_job_rolls_back_and_closes_on_signal_fetch_error():
    fake_db = Mock()
    session_factory = Mock(return_value=fake_db)

    master_repo = Mock()
    master_repo.get_latest_signals.side_effect = RuntimeError("signal fetch failed")

    job = RiskJob(
        session_factory=session_factory,
        master_repo=master_repo,
        risk_repo=Mock(),
        trade_plan_repo=Mock(),
        engine=Mock(),
    )

    summary = job.run()

    assert summary["processed"] == 0
    assert summary["saved"] == 0
    assert summary["failed"] == 0
    assert summary["errors"]

    fake_db.rollback.assert_called_once()
    fake_db.close.assert_called_once()


def test_market_job_rolls_back_and_closes_on_symbol_fetch_error():
    fake_db = Mock()
    sys.modules.setdefault("requests", Mock())
    market_job = importlib.import_module("app.jobs.market_job")

    with patch("app.jobs.market_job.SessionLocal", return_value=fake_db), patch(
        "app.jobs.market_job.SymbolRepository.get_active_symbols",
        side_effect=RuntimeError("boom"),
    ):
        market_job.run_market_job()

    assert fake_db.rollback.called
    assert fake_db.close.called
