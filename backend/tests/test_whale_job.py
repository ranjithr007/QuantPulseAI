import sys
import types
from types import SimpleNamespace
from unittest.mock import Mock, patch

fake_requests = types.ModuleType("requests")
fake_requests.get = lambda *args, **kwargs: None
sys.modules.setdefault("requests", fake_requests)

from app.jobs.whale_job import run_whale_job


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
    ), patch("app.jobs.whale_job.WhaleRepository.save") as whale_save, patch(
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
        run_whale_job()

    assert whale_save.called
    assert flow_save.called
    assert fake_db.close.called
    assert not fake_db.rollback.called
