from datetime import datetime
from datetime import timedelta
from datetime import timezone
from types import SimpleNamespace

from app.repositories.candle_repository import get_candles_as_of
from app.repositories.candle_repository import get_final_candle_series
from app.repositories.candle_repository import get_latest_candle


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *args):
        return self

    def order_by(self, *args):
        return self

    def limit(self, value):
        return self

    def all(self):
        return list(self.rows)


class FakeSession:
    def __init__(self, rows):
        self.rows = rows
        self.info = {}

    def query(self, model):
        return FakeQuery(self.rows)


def test_final_series_is_ascending_deduplicated_and_prefers_verified_source():
    now = datetime.now(timezone.utc)
    older = now - timedelta(hours=3)
    newer = now - timedelta(hours=2)
    rows = [
        _candle(1, newer, "UNKNOWN", "LEGACY_UNVERIFIED", 0.071),
        _candle(2, older, "BINANCE", "VERIFIED", 0.069),
        _candle(3, newer, "BINANCE", "VERIFIED", 0.072),
        _candle(
            4,
            now,
            "BINANCE",
            "PROVISIONAL",
            0.073,
            is_final=False,
        ),
    ]
    db = FakeSession(rows)

    candles = get_final_candle_series(db, "DOGEUSDT", "1h", limit=20)

    assert [candle.id for candle in candles] == [2, 3]
    assert get_latest_candle(db, "DOGEUSDT", "1h").id == 3


def test_as_of_series_excludes_candle_until_its_close_boundary():
    as_of = datetime(2026, 7, 27, 10, 30, tzinfo=timezone.utc)
    closed = _candle(
        1,
        datetime(2026, 7, 27, 9, 0, tzinfo=timezone.utc),
        "BINANCE",
        "VERIFIED",
        0.071,
    )
    not_closed = _candle(
        2,
        datetime(2026, 7, 27, 10, 0, tzinfo=timezone.utc),
        "BINANCE",
        "VERIFIED",
        0.072,
    )

    candles = get_candles_as_of(
        FakeSession([not_closed, closed]),
        "DOGEUSDT",
        "1h",
        as_of,
        limit=20,
    )

    assert [candle.id for candle in candles] == [1]


def _candle(
    identifier,
    open_time,
    venue,
    quality_state,
    close_price,
    *,
    is_final=True,
):
    return SimpleNamespace(
        id=identifier,
        symbol="DOGEUSDT",
        timeframe="1h",
        venue=venue,
        market_type="FUTURES",
        open_time=open_time,
        candle_time=open_time,
        close_time=open_time + timedelta(hours=1),
        is_final=is_final,
        quality_state=quality_state,
        revision=1,
        close_price=close_price,
    )
