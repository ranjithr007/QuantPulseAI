import importlib
import sys
from unittest.mock import Mock, patch

import pytest

from app.api.v1.ml_label_api import create_labels
from app.jobs.ml_label_job import run_ml_label_job


def test_ml_label_job_rolls_back_and_closes_when_symbol_fetch_fails():
    fake_db = Mock()

    with patch("app.jobs.ml_label_job.SessionLocal", return_value=fake_db), patch(
        "app.jobs.ml_label_job.SymbolRepository.get_active_symbols",
        side_effect=RuntimeError("boom"),
    ):
        with pytest.raises(RuntimeError):
            run_ml_label_job()

    assert fake_db.rollback.called
    assert fake_db.close.called


def test_whale_job_rolls_back_and_closes_when_symbol_fetch_fails():
    fake_db = Mock()

    sys.modules.setdefault("requests", Mock())
    whale_job = importlib.import_module("app.jobs.whale_job")

    with patch("app.jobs.whale_job.SessionLocal", return_value=fake_db), patch(
        "app.jobs.whale_job.SymbolRepository.get_active_symbols",
        side_effect=RuntimeError("boom"),
    ):
        whale_job.run_whale_job()

    assert fake_db.rollback.called
    assert fake_db.close.called


def test_label_api_rolls_back_and_closes_when_generation_fails():
    fake_db = Mock()

    with patch("app.api.v1.ml_label_api.SessionLocal", return_value=fake_db), patch(
        "app.api.v1.ml_label_api.LabelGenerator.generate",
        side_effect=RuntimeError("boom"),
    ):
        with pytest.raises(RuntimeError):
            create_labels("BTCUSDT")

    assert fake_db.rollback.called
    assert fake_db.close.called
