import sys
import types
import inspect
from types import SimpleNamespace
from unittest.mock import Mock, patch

fake_requests = types.ModuleType("requests")
fake_requests.get = lambda *args, **kwargs: None
sys.modules.setdefault("requests", fake_requests)

from app.jobs.whale_job import run_whale_job
from app.repositories.orderflow_repository import OrderFlowRepository


def test_get_last_cvd_is_an_instance_method():
    assert list(inspect.signature(OrderFlowRepository.get_last_cvd).parameters) == [
        "self",
        "db",
        "symbol",
    ]


def test_whale_job_continues_when_one_symbol_has_no_data():
    fake_db = SimpleNamespace(close=Mock(), rollback=Mock())
    symbols = [
        SimpleNamespace(symbol="BTCUSDT"),
        SimpleNamespace(symbol="ETHUSDT"),
    ]
    whale_payload = {
        "whales": [
            {
                "symbol": "ETHUSDT",
                "side": "BUY",
                "price": 2000.0,
                "quantity": 1.0,
                "value_usd": 2000.0,
                "trade_time": object(),
            }
        ],
        "delta": 1.0,
    }

    with patch("app.jobs.whale_job.SessionLocal", return_value=fake_db), patch(
        "app.jobs.whale_job.SymbolRepository.get_active_symbols",
        return_value=symbols,
    ), patch(
        "app.jobs.whale_job.WhaleCollector.get_order_flow",
        side_effect=[None, whale_payload],
    ), patch("app.jobs.whale_job.WhaleRepository.save_many") as whale_save, patch(
        "app.jobs.whale_job.OrderFlowRepository.get_last_cvd",
        return_value=0,
    ), patch(
        "app.jobs.whale_job.OrderFlowRepository.get_recent_flow",
        return_value=[],
    ), patch(
        "app.jobs.whale_job.OrderFlowRepository.save"
    ) as flow_save, patch(
        "app.jobs.whale_job.OrderFlowEngine.detect_absorption",
        return_value=("NONE", 0),
    ), patch(
        "app.jobs.whale_job.OrderFlowEngine.detect_exhaustion",
        return_value=("NONE", 0),
    ):
        result = run_whale_job()

    assert whale_save.called
    assert flow_save.called
    assert fake_db.close.called
    assert not fake_db.rollback.called
    assert result == {
        "status": "OK",
        "source": "whale_job",
        "symbols": 2,
        "processed": ["ETHUSDT"],
        "skipped": ["BTCUSDT"],
        "failed": [],
    }


def test_whale_job_isolates_one_symbol_failure_and_processes_the_next():
    fake_db = SimpleNamespace(close=Mock(), rollback=Mock())
    symbols = [
        SimpleNamespace(symbol="BNBUSDT"),
        SimpleNamespace(symbol="BTCUSDT"),
    ]

    def payload(symbol):
        return {
            "symbol": symbol,
            "whales": [],
            "delta": 1.0,
        }

    with patch("app.jobs.whale_job.SessionLocal", return_value=fake_db), patch(
        "app.jobs.whale_job.SymbolRepository.get_active_symbols",
        return_value=symbols,
    ), patch(
        "app.jobs.whale_job.WhaleCollector.get_order_flow",
        side_effect=[payload("BNBUSDT"), payload("BTCUSDT")],
    ), patch("app.jobs.whale_job.WhaleRepository.save_many"), patch(
        "app.jobs.whale_job.OrderFlowRepository.get_last_cvd",
        side_effect=[RuntimeError("bad CVD"), 0],
    ), patch(
        "app.jobs.whale_job.OrderFlowRepository.get_recent_flow",
        return_value=[],
    ), patch(
        "app.jobs.whale_job.OrderFlowRepository.save"
    ) as flow_save, patch(
        "app.jobs.whale_job.OrderFlowEngine.detect_absorption",
        return_value=("NONE", 0),
    ), patch(
        "app.jobs.whale_job.OrderFlowEngine.detect_exhaustion",
        return_value=("NONE", 0),
    ):
        result = run_whale_job()

    assert result["status"] == "DEGRADED"
    assert result["failed"] == ["BNBUSDT"]
    assert result["processed"] == ["BTCUSDT"]
    assert flow_save.call_count == 1
    assert fake_db.rollback.call_count == 1
    assert fake_db.close.call_count == 1
