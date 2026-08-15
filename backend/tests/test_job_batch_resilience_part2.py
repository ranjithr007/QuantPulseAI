from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.jobs.fusion_job import run_fusion_job
from app.jobs.ml_dataset_job import run_ml_dataset_job
from app.jobs.orderflow_jobs import run_orderflow_job
from app.jobs.paper_trade_monitor_job import run_paper_trade_monitor_job


def test_run_orderflow_job_continues_after_timeframe_error():
    fake_db = SimpleNamespace(close=Mock())
    symbols = [SimpleNamespace(symbol="BTCUSDT")]

    def generate_orderflow(symbol, timeframe):
        if timeframe == "5m":
            raise RuntimeError("boom")
        return {"symbol": symbol, "timeframe": timeframe}

    with patch("app.jobs.orderflow_jobs.SessionLocal", return_value=fake_db), patch(
        "app.jobs.orderflow_jobs.SymbolRepository.get_active_symbols",
        return_value=symbols,
    ), patch(
        "app.jobs.orderflow_jobs.generate_orderflow",
        side_effect=generate_orderflow,
    ) as generate_orderflow:
        run_orderflow_job()

    assert generate_orderflow.called
    assert fake_db.close.called


def test_run_fusion_job_continues_after_timeframe_error():
    fake_db = SimpleNamespace(close=Mock())
    symbols = [SimpleNamespace(symbol="BTCUSDT")]

    class FakeService:
        def generate(self, db, symbol, timeframe):
            if timeframe == "1m":
                raise RuntimeError("boom")
            return {"decision": "LONG"}

    with patch("app.jobs.fusion_job.SessionLocal", return_value=fake_db), patch(
        "app.jobs.fusion_job.SymbolRepository.get_active_symbols",
        return_value=symbols,
    ), patch(
        "app.jobs.fusion_job.service",
        FakeService(),
    ):
        run_fusion_job()

    assert fake_db.close.called


def test_run_paper_trade_monitor_job_continues_after_trade_error():
    fake_db = SimpleNamespace(close=Mock())
    trades = [SimpleNamespace(symbol="BTCUSDT"), SimpleNamespace(symbol="ETHUSDT")]
    candle = SimpleNamespace()

    class FakeRepo:
        def get_open_trades(self, db):
            return trades

        def ensure_staged_exit_policy(self, db, trade):
            return False

        def close_trade(self, *args, **kwargs):
            return SimpleNamespace(id=1, pnl_percent=1.0, result="WIN")

    with patch("app.jobs.paper_trade_monitor_job.SessionLocal", return_value=fake_db), patch(
        "app.jobs.paper_trade_monitor_job.PaperTradeRepository",
        return_value=FakeRepo(),
    ), patch(
        "app.jobs.paper_trade_monitor_job.get_final_candles_after",
        side_effect=[RuntimeError("boom"), [candle]],
    ), patch(
        "app.jobs.paper_trade_monitor_job.evaluate_paper_trade_exit",
        return_value={"action": "CLOSE", "exit_price": 101.0, "result": "WIN"},
    ):
        summary = run_paper_trade_monitor_job()

    assert summary["processed"] == 2
    assert summary["closed"] == 1
    assert fake_db.close.called


def test_run_ml_dataset_job_continues_after_symbol_error():
    fake_db = SimpleNamespace(close=Mock())
    symbols = [SimpleNamespace(symbol="BTCUSDT"), SimpleNamespace(symbol="ETHUSDT")]
    builder = Mock()
    builder.build.side_effect = [RuntimeError("boom"), {"rows": 1}, {"rows": 2}]

    with patch("app.jobs.ml_dataset_job.SessionLocal", return_value=fake_db), patch(
        "app.jobs.ml_dataset_job.SymbolRepository.get_active_symbols",
        return_value=symbols,
    ), patch(
        "app.jobs.ml_dataset_job.DatasetBuilder",
        return_value=builder,
    ):
        run_ml_dataset_job()

    assert builder.build.call_count == 3
    assert fake_db.close.called
