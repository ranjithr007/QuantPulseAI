import sys
import types
from types import SimpleNamespace
from unittest.mock import Mock, patch

fake_websockets = types.ModuleType("websockets")
fake_websockets.connect = lambda *args, **kwargs: None
sys.modules.setdefault("websockets", fake_websockets)

from app.jobs.liquidation_job import save_event


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
        "app.jobs.liquidation_job.LiquidationRepository.save",
        side_effect=RuntimeError("boom"),
    ):
        save_event(event)

    assert fake_db.close.called
