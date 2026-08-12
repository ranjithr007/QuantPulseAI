from datetime import datetime
from datetime import timedelta
from datetime import timezone
import gzip
import json
from unittest.mock import Mock

from app.governance.candle_history_backfill import backfill_canonical_candles
from app.governance.candle_history_backfill import load_checkpoint
from app.governance.candle_history_backfill import import_canonical_candle_cache
from app.governance.candle_history_backfill import required_candle_counts


def test_governed_history_requirements_cover_six_official_folds():
    assert required_candle_counts() == {
        "1h": 12960,
        "2h": 6480,
        "4h": 3240,
        "1d": 540,
    }


def test_canonical_candle_backfill_is_resumable_and_audited(tmp_path):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(hours=2)
    open_ms = int(start.timestamp() * 1000)
    collector = Mock()
    collector.get_candles.side_effect = [
        [{"open_time_ms": open_ms}],
        [],
    ]
    fallback = Mock()
    fallback.get_candles.return_value = []
    repository = Mock()
    repository.insert_final_candles_batch.return_value = {
        "inserted": 1,
        "existing": 0,
        "rejected": 0,
    }
    db = Mock()
    checkpoint_path = tmp_path / "candles.json"

    result = backfill_canonical_candles(
        symbols=["dogeusdt"],
        timeframes=["1h"],
        start=start,
        end=end,
        checkpoint_path=checkpoint_path,
        primary_collector=collector,
        fallback_collector=fallback,
        repository=repository,
        session_factory=lambda: db,
        readiness_auditor=lambda **_kwargs: {
            "ready": True,
            "ready_scopes": 1,
            "total_scopes": 1,
            "records": [],
        },
    )

    checkpoint = load_checkpoint(checkpoint_path)
    scope = checkpoint["scopes"]["DOGEUSDT:1h"]
    assert result["status"] == "COMPLETE"
    assert result["inserted"] == 1
    assert scope["status"] == "COMPLETE"
    assert scope["inserted"] == 1
    repository.insert_final_candles_batch.assert_called_once_with(
        db,
        [{"open_time_ms": open_ms}],
    )
    assert db.close.called


def test_canonical_candle_backfill_dry_run_has_no_side_effects(tmp_path):
    session_factory = Mock()
    collector = Mock()
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)

    result = backfill_canonical_candles(
        symbols=["BTCUSDT", "ETHUSDT"],
        timeframes=["1h", "2h", "4h", "1d"],
        start=start,
        end=start + timedelta(days=550),
        checkpoint_path=tmp_path / "checkpoint.json",
        primary_collector=collector,
        session_factory=session_factory,
        dry_run=True,
    )

    assert result["status"] == "DRY_RUN"
    assert result["total_scopes"] == 8
    assert result["required_candle_counts"]["2h"] == 6480
    session_factory.assert_not_called()
    collector.get_candles.assert_not_called()


def test_canonical_candle_backfill_rejects_non_governed_timeframe(tmp_path):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    try:
        backfill_canonical_candles(
            symbols=["BTCUSDT"],
            timeframes=["15m"],
            start=start,
            end=start + timedelta(days=1),
            checkpoint_path=tmp_path / "checkpoint.json",
            dry_run=True,
        )
    except ValueError as exc:
        assert "15m" in str(exc)
    else:
        raise AssertionError("15m must not enter the governed candle backfill")


def test_portable_cache_import_uses_normal_canonical_batch_path(tmp_path):
    cache_path = tmp_path / "candles.jsonl.gz"
    candle = {
        "symbol": "BTCUSDT",
        "timeframe": "2h",
        "venue": "BINANCE",
        "market_type": "FUTURES",
        "source": "BINANCE_FUTURES_REST",
        "open_time_ms": 1_767_225_600_000,
        "close_time_ms": 1_767_232_800_000,
        "is_final": True,
        "open": 100,
        "high": 110,
        "low": 90,
        "close": 105,
        "volume": 1000,
    }
    with gzip.open(cache_path, "wt", encoding="utf-8") as handle:
        handle.write(json.dumps(candle) + "\n")
    repository = Mock()
    repository.insert_final_candles_batch.return_value = {
        "inserted": 1,
        "existing": 0,
        "rejected": 0,
    }
    db = Mock()

    result = import_canonical_candle_cache(
        path=cache_path,
        symbols=["BTCUSDT"],
        timeframes=["2h"],
        repository=repository,
        session_factory=lambda: db,
        readiness_auditor=lambda **_kwargs: {
            "ready": True,
            "ready_scopes": 1,
            "total_scopes": 1,
            "records": [],
        },
    )

    assert result["status"] == "COMPLETE"
    assert result["inserted"] == 1
    repository.insert_final_candles_batch.assert_called_once_with(db, [candle])
    assert db.close.called
