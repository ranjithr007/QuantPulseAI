import importlib
import sys
from unittest.mock import Mock, patch

from app.jobs.ai_signal_job import run_ai_signal_job
from app.jobs.master_ai_job import run_master_ai_job


def test_ai_signal_job_rolls_back_and_closes_on_query_error():
    fake_db = Mock()

    with patch("app.jobs.ai_signal_job.SessionLocal", return_value=fake_db), patch(
        "app.jobs.ai_signal_job.LiquiditySignal"
    ), patch("app.jobs.ai_signal_job.LiquidationHeatmap"), patch(
        "app.jobs.ai_signal_job.AISignalRepository.save",
        side_effect=RuntimeError("boom"),
    ):
        run_ai_signal_job()

    assert fake_db.rollback.called
    assert fake_db.close.called


def test_master_ai_job_rolls_back_and_closes_on_symbol_fetch_error():
    fake_db = Mock()

    with patch("app.jobs.master_ai_job.SessionLocal", return_value=fake_db), patch(
        "app.jobs.master_ai_job.SymbolRepository.get_active_symbols",
        side_effect=RuntimeError("boom"),
    ):
        run_master_ai_job()

    assert fake_db.rollback.called
    assert fake_db.close.called


def test_derivative_job_rolls_back_and_closes_on_symbol_fetch_error():
    fake_db = Mock()
    sys.modules.setdefault("requests", Mock())
    derivative_job = importlib.import_module("app.jobs.derivative_job")

    with patch("app.jobs.derivative_job.SessionLocal", return_value=fake_db), patch(
        "app.jobs.derivative_job.SymbolRepository.get_active_symbols",
        side_effect=RuntimeError("boom"),
    ):
        derivative_job.run_derivative_job()

    assert fake_db.rollback.called
    assert fake_db.close.called
