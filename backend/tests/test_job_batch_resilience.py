from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.jobs.intelligence_job import run_intelligence_job
from app.jobs.pipeline_cycle_job import run_pipeline_cycle_job
from app.jobs.signal_quality_job import run_signal_quality_job
from app.jobs.smc_job import run_smc_job
from app.jobs.whale_intelligence_job import run_whale_intelligence_job


def test_run_intelligence_job_continues_after_symbol_error():
    fake_db = SimpleNamespace(close=Mock())
    symbols = [SimpleNamespace(symbol="BTCUSDT"), SimpleNamespace(symbol="ETHUSDT")]

    with patch("app.jobs.intelligence_job.SessionLocal", return_value=fake_db), patch(
        "app.jobs.intelligence_job.SymbolRepository.get_active_symbols",
        return_value=symbols,
    ), patch(
        "app.jobs.intelligence_job.MarketFeatureBuilder.build",
        side_effect=[
            RuntimeError("boom"),
            {"funding": 1, "oi_change": 2, "price_change": 3},
        ],
    ), patch(
        "app.jobs.intelligence_job.LiquidityEngine.analyze",
        return_value={"symbol": "ETHUSDT"},
    ), patch(
        "app.jobs.intelligence_job.LiquidityRepository.save"
    ) as save:
        run_intelligence_job()

    assert save.called
    assert fake_db.close.called


def test_run_signal_quality_job_continues_after_signal_error():
    fake_db = SimpleNamespace(close=Mock(), query=Mock())
    signals = [SimpleNamespace(symbol="BTCUSDT"), SimpleNamespace(symbol="ETHUSDT")]

    class FakeQuery:
        def order_by(self, *args, **kwargs):
            return self

        def limit(self, *args, **kwargs):
            return self

        def all(self):
            return signals

    fake_db.query.return_value = FakeQuery()

    with patch("app.jobs.signal_quality_job.SessionLocal", return_value=fake_db), patch(
        "app.jobs.signal_quality_job.SignalQualityEngine.analyze",
        side_effect=[RuntimeError("boom"), {"symbol": "ETHUSDT"}],
    ), patch("app.jobs.signal_quality_job.SignalQualityRepository.save") as save:
        run_signal_quality_job()

    assert save.called
    assert fake_db.close.called


def test_run_whale_intelligence_job_continues_after_symbol_error():
    fake_db = SimpleNamespace(close=Mock())
    symbols = [SimpleNamespace(symbol="BTCUSDT"), SimpleNamespace(symbol="ETHUSDT")]

    with patch(
        "app.jobs.whale_intelligence_job.SessionLocal", return_value=fake_db
    ), patch(
        "app.jobs.whale_intelligence_job.SymbolRepository.get_active_symbols",
        return_value=symbols,
    ), patch(
        "app.jobs.whale_intelligence_job.WhaleEngine.analyze",
        side_effect=[RuntimeError("boom"), {"symbol": "ETHUSDT"}],
    ), patch(
        "app.jobs.whale_intelligence_job.WhaleSignalRepository.save"
    ) as save:
        run_whale_intelligence_job()

    assert save.called
    assert fake_db.close.called


def test_run_smc_job_continues_after_timeframe_error():
    fake_db = SimpleNamespace(close=Mock(), query=Mock())
    symbols = [SimpleNamespace(symbol="BTCUSDT")]
    candles = [SimpleNamespace(id=_ + 1, close_price=100.0) for _ in range(20)]

    class FakeQuery:
        def filter(self, *args, **kwargs):
            return self

        def order_by(self, *args, **kwargs):
            return self

        def limit(self, *args, **kwargs):
            return self

        def all(self):
            return candles

    fake_db.query.return_value = FakeQuery()

    with patch("app.jobs.smc_job.SessionLocal", return_value=fake_db), patch(
        "app.jobs.smc_job.SymbolRepository.get_active_symbols",
        return_value=symbols,
    ), patch(
        "app.jobs.smc_job.TIMEFRAMES",
        ["5m", "15m"],
    ), patch(
        "app.jobs.smc_job.engine.analyze",
        side_effect=[RuntimeError("boom"), {"structure": "UPTREND"}],
    ), patch(
        "app.jobs.smc_job.smc_repo.save"
    ) as save:
        run_smc_job()

    assert save.called
    assert fake_db.close.called


def test_pipeline_cycle_job_reports_failed_stage_and_continues():
    with patch(
        "app.jobs.pipeline_cycle_job.run_watchlist_persist_job",
        return_value={"status": "OK"},
    ), patch(
        "app.jobs.pipeline_cycle_job.run_risk_job",
        side_effect=RuntimeError("risk failed"),
    ), patch(
        "app.jobs.pipeline_cycle_job.run_paper_trade_execute_job",
        return_value={"status": "OK"},
    ), patch(
        "app.jobs.pipeline_cycle_job.run_paper_trade_monitor_job",
        return_value={"status": "OK"},
    ):
        result = run_pipeline_cycle_job()

    assert result["status"] == "PARTIAL"
    assert result["results"]["risk"]["status"] == "FAILED"
    assert result["results"]["paper_trade_execute"]["status"] == "OK"
