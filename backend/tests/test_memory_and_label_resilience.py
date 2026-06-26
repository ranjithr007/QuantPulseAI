from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.intelligence.memory.trade_memory_engine import TradeMemoryEngine
from app.jobs.ml_label_job import run_ml_label_job


def test_trade_memory_engine_continues_after_trade_error():
    trades = [
        SimpleNamespace(symbol="BTCUSDT"),
        SimpleNamespace(symbol="ETHUSDT"),
    ]

    class FakeTracker:
        def evaluate(self, trade, price):
            if trade.symbol == "BTCUSDT":
                raise RuntimeError("boom")
            return "WIN"

    class FakeRepo:
        def close_trade(self, db, trade, price, result):
            return SimpleNamespace(symbol=trade.symbol, result=result)

    engine = TradeMemoryEngine()
    engine.tracker = FakeTracker()
    engine.repo = FakeRepo()

    updated = engine.process(
        db=SimpleNamespace(),
        trades=trades,
        price_provider=lambda symbol: 100.0,
    )

    assert len(updated) == 1
    assert updated[0].symbol == "ETHUSDT"


def test_ml_label_job_continues_after_symbol_error():
    fake_db = SimpleNamespace(close=Mock(), rollback=Mock())
    symbols = [SimpleNamespace(symbol="BTCUSDT"), SimpleNamespace(symbol="ETHUSDT")]

    with patch("app.jobs.ml_label_job.SessionLocal", return_value=fake_db), patch(
        "app.jobs.ml_label_job.SymbolRepository.get_active_symbols",
        return_value=symbols,
    ), patch(
        "app.jobs.ml_label_job.LabelGenerator.generate",
        side_effect=[RuntimeError("boom"), {"status": "OK"}],
    ) as generate:
        run_ml_label_job()

    assert generate.called
    assert fake_db.close.called
