import asyncio
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

fake_websockets = types.ModuleType("websockets")
fake_websockets.connect = lambda *args, **kwargs: None
sys.modules.setdefault("websockets", fake_websockets)

from app.jobs.liquidation_job import run_liquidation_job_async, save_event


def test_save_event_swallows_repository_failures_and_closes_db():
    fake_db = SimpleNamespace(close=Mock())
    event = {
        "symbol": "BTCUSDT",
        "side": "SELL",
        "price": 65000.0,
        "quantity": 0.25,
        "value_usd": 16250.0,
        "event_time": object(),
    }

    with patch("app.jobs.liquidation_job.SessionLocal", return_value=fake_db), patch(
        "app.jobs.liquidation_job.LiquidationRepository.save_if_new",
        side_effect=RuntimeError("boom"),
    ):
        created = save_event(event)

    assert created is False
    assert fake_db.close.called


def test_save_event_reports_whether_event_was_newly_inserted():
    fake_db = SimpleNamespace(close=Mock())
    event = {
        "symbol": "BTCUSDT",
        "side": "SELL",
        "price": 65000.0,
        "quantity": 0.25,
        "value_usd": 16250.0,
        "event_time": object(),
    }

    with patch("app.jobs.liquidation_job.SessionLocal", return_value=fake_db), patch(
        "app.jobs.liquidation_job.LiquidationRepository.save_if_new",
        return_value=(object(), True),
    ):
        assert save_event(event) is True

    assert fake_db.close.called


def test_continuous_job_counts_duplicates_as_received_but_not_saved():
    fake_databases = [SimpleNamespace(close=Mock()), SimpleNamespace(close=Mock())]
    event = {
        "symbol": "BTCUSDT",
        "side": "SELL",
        "price": 65000.0,
        "quantity": 0.25,
        "value_usd": 16250.0,
        "event_time": object(),
    }

    async def listen(callback):
        callback(event)
        callback(event)

    collector = SimpleNamespace(listen=listen)
    with patch(
        "app.jobs.liquidation_job.LiquidationCollector", return_value=collector
    ), patch(
        "app.jobs.liquidation_job.SessionLocal", side_effect=fake_databases
    ), patch(
        "app.jobs.liquidation_job.LiquidationRepository.save_if_new",
        side_effect=[(object(), True), (object(), False)],
    ):
        result = asyncio.run(run_liquidation_job_async())

    assert result["received"] == 2
    assert result["saved"] == 1
    assert all(database.close.called for database in fake_databases)


def test_continuous_liquidation_job_does_not_log_every_event_payload():
    source = (
        Path(__file__).parents[1] / "app" / "jobs" / "liquidation_job.py"
    ).read_text(encoding="utf-8")

    assert "LIQUIDATION EVENT RECEIVED" not in source
    assert "Liquidation event saved successfully" not in source
    assert "print(event)" not in source
