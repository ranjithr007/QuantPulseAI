from datetime import datetime
from datetime import timezone
from types import SimpleNamespace

from app.market_data.reconciliation import load_reconciliation_checkpoint
from app.market_data.reconciliation import new_reconciliation_checkpoint
from app.market_data.reconciliation import reconcile_scope


HOUR = 3_600_000


class FakeCollector:
    def __init__(self, candles):
        self.candles = candles
        self.calls = []

    def get_candles(self, symbol, **kwargs):
        self.calls.append((symbol, kwargs))
        return list(self.candles)


class FakeRepository:
    def __init__(self):
        self.rows = []

    def upsert_candle(self, db, candle, *, commit=True):
        self.rows.append(
            SimpleNamespace(
                open_time=datetime.fromtimestamp(
                    candle["open_time_ms"] / 1000,
                    timezone.utc,
                ).replace(tzinfo=None),
                candle_time=datetime.fromtimestamp(
                    candle["open_time_ms"] / 1000,
                    timezone.utc,
                ).replace(tzinfo=None),
                is_final=True,
            )
        )
        return "INSERTED"

    def get_source_candles(
        self,
        db,
        symbol,
        timeframe,
        venue,
        start_time,
        end_time,
    ):
        return list(self.rows)


def test_reconciliation_persists_resumable_scope_checkpoint(tmp_path):
    checkpoint_path = tmp_path / "checkpoint.json"
    checkpoint = new_reconciliation_checkpoint()
    collector = FakeCollector([_candle(0), _candle(HOUR)])
    repository = FakeRepository()

    result = reconcile_scope(
        object(),
        repository,
        collector,
        symbol="DOGEUSDT",
        timeframe="1h",
        start_time_ms=0,
        end_time_ms=HOUR * 2,
        checkpoint=checkpoint,
        checkpoint_path=checkpoint_path,
        page_size=2,
        max_pages=1,
    )

    saved = load_reconciliation_checkpoint(checkpoint_path)
    scope = saved["scopes"]["DOGEUSDT:1h"]
    assert result["status"] == "PASS"
    assert result["sequence"]["status"] == "PASS"
    assert result["write_status_counts"] == {"INSERTED": 2}
    assert scope["status"] == "COMPLETE"
    assert scope["start_time_ms"] == 0
    assert scope["next_start_time_ms"] == HOUR * 2


def test_expanding_window_resets_checkpoint_cursor(tmp_path):
    checkpoint_path = tmp_path / "checkpoint.json"
    checkpoint = new_reconciliation_checkpoint()
    checkpoint["scopes"]["DOGEUSDT:1h"] = {
        "symbol": "DOGEUSDT",
        "timeframe": "1h",
        "start_time_ms": HOUR * 10,
        "next_start_time_ms": HOUR * 20,
        "end_time_ms": HOUR * 20,
        "status": "COMPLETE",
        "pages_processed": 1,
    }
    collector = FakeCollector([_candle(0), _candle(HOUR)])

    reconcile_scope(
        object(),
        FakeRepository(),
        collector,
        symbol="DOGEUSDT",
        timeframe="1h",
        start_time_ms=0,
        end_time_ms=HOUR * 2,
        checkpoint=checkpoint,
        checkpoint_path=checkpoint_path,
        page_size=2,
        max_pages=1,
    )

    assert collector.calls[0][1]["start_time_ms"] == 0


def _candle(open_time_ms):
    return {
        "symbol": "DOGEUSDT",
        "timeframe": "1h",
        "open_time_ms": open_time_ms,
        "is_final": True,
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.5,
        "volume": 1000.0,
    }
