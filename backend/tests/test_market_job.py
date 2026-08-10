import sys
import types
from datetime import datetime
from datetime import timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

fake_requests = types.ModuleType("requests")
fake_requests.get = lambda *args, **kwargs: None
sys.modules.setdefault("requests", fake_requests)

from app.jobs.market_job import run_market_job


def test_market_job_continues_after_one_timeframe_failure():
    fake_db = make_fake_db()
    symbol = SimpleNamespace(symbol="BTCUSDT")
    candle = {
        "symbol": "BTCUSDT",
        "timeframe": "5m",
        "open_time_ms": 1000,
        "open": 1.0,
        "high": 2.0,
        "low": 0.5,
        "close": 1.5,
        "volume": 10.0,
    }

    with patch("app.jobs.market_job.SessionLocal", return_value=fake_db), patch(
        "app.jobs.market_job.SymbolRepository.get_active_symbols",
        return_value=[symbol],
    ), patch(
        "app.jobs.market_job.MarketRepository.get_collection_cursor",
        return_value=None,
    ), patch(
        "app.jobs.market_job.CandleCollector.get_candles",
        side_effect=[RuntimeError("boom"), [candle]],
    ), patch(
        "app.jobs.market_job.MarketRepository.save_candle"
    ) as save_candle:
        run_market_job()

    assert save_candle.called
    assert fake_db.close.called


def test_market_job_uses_bybit_fallback_when_binance_returns_no_candles():
    fake_db = make_fake_db()
    symbol = SimpleNamespace(symbol="BTCUSDT")
    candle = {
        "symbol": "BTCUSDT",
        "timeframe": "5m",
        "open_time_ms": 1000,
        "open": 1.0,
        "high": 2.0,
        "low": 0.5,
        "close": 1.5,
        "volume": 10.0,
    }

    with patch("app.jobs.market_job.SessionLocal", return_value=fake_db), patch(
        "app.jobs.market_job.SymbolRepository.get_active_symbols",
        return_value=[symbol],
    ), patch(
        "app.jobs.market_job.MarketRepository.get_collection_cursor",
        return_value=None,
    ), patch(
        "app.jobs.market_job.CandleCollector.get_candles",
        return_value=[],
    ) as binance_get, patch(
        "app.jobs.market_job.BybitCandleCollector.get_candles",
        return_value=[candle],
    ) as bybit_get, patch(
        "app.jobs.market_job.MarketRepository.save_candle"
    ) as save_candle:
        run_market_job()

    assert binance_get.called
    assert bybit_get.called
    assert save_candle.called
    assert fake_db.close.called


def test_market_job_suppresses_transient_connection_errors():
    fake_db = make_fake_db()
    symbol = SimpleNamespace(symbol="BTCUSDT")

    with patch("app.jobs.market_job.SessionLocal", return_value=fake_db), patch(
        "app.jobs.market_job.SymbolRepository.get_active_symbols",
        return_value=[symbol],
    ), patch("app.jobs.market_job.TIMEFRAMES", ["5m"]), patch(
        "app.jobs.market_job.CandleCollector.get_candles",
        side_effect=ConnectionResetError(
            10054,
            "An existing connection was forcibly closed by the remote host",
            None,
            10054,
            None,
        ),
    ), patch(
        "app.jobs.market_job.BybitCandleCollector.get_candles",
        return_value=[],
    ), patch(
        "app.jobs.market_job.MarketRepository.get_collection_cursor",
        return_value=None,
    ), patch(
        "app.jobs.market_job.MarketRepository.save_candle"
    ), patch("builtins.print") as print_mock:
        run_market_job()

    error_messages = [
        " ".join(str(part) for part in call.args)
        for call in print_mock.call_args_list
    ]
    assert not any("Market job error" in message for message in error_messages)


def test_market_job_reprocesses_latest_identity_so_forming_candle_can_finalize():
    fake_db = make_fake_db()
    symbol = SimpleNamespace(symbol="BTCUSDT")
    candle = {
        "symbol": "BTCUSDT",
        "timeframe": "1h",
        "open_time_ms": 1_000,
        "open": 1.0,
        "high": 2.0,
        "low": 0.5,
        "close": 1.5,
        "volume": 10.0,
    }

    with patch("app.jobs.market_job.SessionLocal", return_value=fake_db), patch(
        "app.jobs.market_job.SymbolRepository.get_active_symbols",
        return_value=[symbol],
    ), patch("app.jobs.market_job.TIMEFRAMES", ["1h"]), patch(
        "app.jobs.market_job.MarketRepository.get_collection_cursor",
        return_value=SimpleNamespace(
            open_time=datetime.now(timezone.utc).replace(
                minute=0,
                second=0,
                microsecond=0,
            ),
            is_final=False,
        ),
    ), patch(
        "app.jobs.market_job.CandleCollector.get_candles",
        return_value=[candle],
    ), patch(
        "app.jobs.market_job.MarketRepository.save_candle",
        return_value=True,
    ) as save_candle:
        result = run_market_job()

    save_candle.assert_called_once_with(fake_db, candle)
    assert result["status"] == "COMPLETED"
    assert result["rows_written"] == 1


def test_market_job_fails_when_all_sources_return_no_candles():
    fake_db = make_fake_db()
    symbol = SimpleNamespace(symbol="BTCUSDT")

    with patch("app.jobs.market_job.SessionLocal", return_value=fake_db), patch(
        "app.jobs.market_job.SymbolRepository.get_active_symbols",
        return_value=[symbol],
    ), patch("app.jobs.market_job.TIMEFRAMES", ["1h"]), patch(
        "app.jobs.market_job.MarketRepository.get_collection_cursor",
        return_value=None,
    ), patch(
        "app.jobs.market_job.CandleCollector.get_candles",
        return_value=[],
    ), patch(
        "app.jobs.market_job.BybitCandleCollector.get_candles",
        return_value=[],
    ), patch(
        "app.jobs.market_job.MarketRepository.save_candle"
    ) as save_candle:
        result = run_market_job()

    assert result["status"] == "FAILED"
    assert result["total_failed"] == 1
    assert result["rows_written"] == 0
    assert result["results"][0]["error"] == "NO_CANDLES_FROM_AVAILABLE_SOURCES"
    save_candle.assert_not_called()


def make_fake_db():
    return SimpleNamespace(
        commit=Mock(),
        rollback=Mock(),
        close=Mock(),
    )
