from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.jobs.backtest_job import run_backtest_job


def test_backtest_job_continues_after_one_signal_error():
    fake_db = SimpleNamespace(close=Mock(), query=Mock())
    signal_a = SimpleNamespace(symbol="BTCUSDT")
    signal_b = SimpleNamespace(symbol="ETHUSDT")

    class FakeQuery:
        def filter(self, *args, **kwargs):
            return self

        def limit(self, *args, **kwargs):
            return self

        def all(self):
            return [signal_a, signal_b]

    with patch("app.jobs.backtest_job.SessionLocal", return_value=fake_db), patch(
        "app.jobs.backtest_job.BacktestEngine.test",
        side_effect=[RuntimeError("boom"), {"symbol": "ETHUSDT", "signal": "LONG"}],
    ) as test, patch(
        "app.jobs.backtest_job.BacktestRepository.save"
    ) as save, patch(
        "app.jobs.backtest_job.MasterSignal"
    ) as master_signal:
        fake_db.query.return_value = FakeQuery()
        run_backtest_job()

    assert test.called
    assert save.called
    assert fake_db.close.called
