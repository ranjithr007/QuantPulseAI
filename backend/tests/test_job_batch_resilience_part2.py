from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.jobs.fusion_job import run_fusion_job
from app.jobs.ml_dataset_job import run_ml_dataset_job
from app.jobs.orderflow_jobs import run_orderflow_job
from app.jobs.paper_trade_monitor_job import run_paper_trade_monitor_job


def test_run_orderflow_job_continues_after_timeframe_error():
    fake_db = SimpleNamespace(close=Mock())
    symbols = [SimpleNamespace(symbol="BTCUSDT")]

    def generate_orderflow(symbol, timeframe, context=None):
        if timeframe == "2h":
            raise RuntimeError("boom")
        return {"symbol": symbol, "timeframe": timeframe}

    with patch("app.jobs.orderflow_jobs.SessionLocal", return_value=fake_db), patch(
        "app.jobs.orderflow_jobs.SymbolRepository.get_active_symbols",
        return_value=symbols,
    ), patch(
        "app.jobs.orderflow_jobs.generate_orderflow",
        side_effect=generate_orderflow,
    ) as generate_orderflow:
        result = run_orderflow_job()

    assert generate_orderflow.called
    assert result["status"] == "DEGRADED"
    assert result["expected_count"] == 4
    assert result["saved_count"] == 3
    assert result["failed_count"] == 1
    assert result["errors"][0]["timeframe"] == "2h"
    assert fake_db.close.called


def test_run_orderflow_job_fails_when_no_timeframe_is_saved():
    fake_db = SimpleNamespace(close=Mock())
    symbols = [SimpleNamespace(symbol="BTCUSDT")]

    with patch("app.jobs.orderflow_jobs.SessionLocal", return_value=fake_db), patch(
        "app.jobs.orderflow_jobs.SymbolRepository.get_active_symbols",
        return_value=symbols,
    ), patch(
        "app.jobs.orderflow_jobs.generate_orderflow",
        side_effect=RuntimeError("boom"),
    ):
        result = run_orderflow_job()

    assert result["status"] == "FAILED"
    assert result["saved_count"] == 0
    assert result["failed_count"] == 4
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
    assert summary["status"] == "FAILED"
    assert fake_db.close.called


def test_strategy_paper_monitor_error_degrades_without_failing_official_monitor():
    fake_db = SimpleNamespace(close=Mock())

    class FakeRepo:
        def get_open_trades(self, db):
            return []

    shadow = {
        "source": "strategy_shadow_monitor_v1",
        "processed": 1,
        "closed": 0,
        "partial_closes": 0,
        "stop_moves": 0,
        "still_open": 1,
        "errors": ["REGIME_TREND_ENTRY SOLUSDT: EXIT_EVIDENCE_UNAVAILABLE"],
        "records": [],
    }
    with patch(
        "app.jobs.paper_trade_monitor_job.SessionLocal",
        return_value=fake_db,
    ), patch(
        "app.jobs.paper_trade_monitor_job.PaperTradeRepository",
        return_value=FakeRepo(),
    ), patch(
        "app.jobs.paper_trade_monitor_job._run_strategy_shadow_monitor",
        return_value=shadow,
    ):
        summary = run_paper_trade_monitor_job()

    assert summary["status"] == "DEGRADED"
    assert summary["errors"] == []
    assert summary["shadow"]["errors"] == shadow["errors"]
    assert fake_db.close.called


def test_resolved_intrabar_overlap_warns_without_failing_official_monitor():
    checkpoint = datetime.utcnow()
    trade = SimpleNamespace(
        id=1,
        symbol="BNBUSDT",
        side="SHORT",
        opened_at=checkpoint - timedelta(hours=1),
        last_exit_evaluated_at=checkpoint,
    )
    candle = SimpleNamespace(
        open_time=checkpoint - timedelta(minutes=2),
        close_time=checkpoint + timedelta(minutes=3),
        candle_time=checkpoint - timedelta(minutes=2),
        high_price=725.0,
        low_price=723.0,
        close_price=724.0,
        live_mark=False,
    )
    fake_db = SimpleNamespace(close=Mock(), flush=Mock())

    class FakeRepo:
        def get_open_trades(self, db):
            return [trade]

        def ensure_staged_exit_policy(self, db, item):
            return False

        def mark_exit_evaluated(self, db, item, evaluated_at):
            item.last_exit_evaluated_at = evaluated_at

    with patch(
        "app.jobs.paper_trade_monitor_job.SessionLocal",
        return_value=fake_db,
    ), patch(
        "app.jobs.paper_trade_monitor_job.PaperTradeRepository",
        return_value=FakeRepo(),
    ), patch(
        "app.jobs.paper_trade_monitor_job._exit_candles",
        return_value=([candle], "5m", False, True),
    ), patch(
        "app.jobs.paper_trade_monitor_job.lock_open_trade",
        side_effect=lambda db, item: item,
    ), patch(
        "app.jobs.paper_trade_monitor_job.evaluate_paper_trade_exit",
        return_value={"action": "HOLD", "result": "OPEN"},
    ), patch(
        "app.jobs.paper_trade_monitor_job._run_strategy_shadow_monitor",
        return_value={"errors": [], "warnings": []},
    ):
        summary = run_paper_trade_monitor_job()

    assert summary["status"] == "OK"
    assert summary["errors"] == []
    assert summary["warnings"] == [
        "BNBUSDT: INTRABAR_RECOVERY_AMBIGUOUS_CLOSE_ONLY"
    ]
    assert summary["candles_evaluated"] == 1


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
