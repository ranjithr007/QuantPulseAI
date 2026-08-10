from datetime import datetime
from datetime import timezone
from types import SimpleNamespace
from unittest.mock import Mock

from app.repositories.market_repository import MarketRepository


NOW = datetime(2026, 7, 26, 12, 30, tzinfo=timezone.utc)
OPEN_TIME_MS = int(datetime(2026, 7, 26, 12, tzinfo=timezone.utc).timestamp() * 1000)
CLOSE_TIME_MS = int(datetime(2026, 7, 26, 13, tzinfo=timezone.utc).timestamp() * 1000)


def test_canonical_candle_is_inserted_as_provisional():
    db = _db(existing=None)

    status = MarketRepository().upsert_candle(
        db,
        _candle(is_final=False),
        now=NOW,
    )

    assert status == "INSERTED"
    entity = db.add.call_args.args[0]
    assert entity.venue == "BINANCE"
    assert entity.market_type == "FUTURES"
    assert entity.open_time == datetime(2026, 7, 26, 12)
    assert entity.close_time == datetime(2026, 7, 26, 13)
    assert entity.candle_time == entity.open_time
    assert entity.is_final is False
    assert entity.quality_state == "PROVISIONAL"
    assert entity.revision == 1
    db.commit.assert_called_once()


def test_provisional_candle_updates_and_then_finalizes():
    existing = _existing()
    db = _db(existing=existing)
    repository = MarketRepository()

    updated = repository.upsert_candle(
        db,
        _candle(high=2.2, close=1.8, volume=15, is_final=False),
        now=NOW,
    )
    finalized = repository.upsert_candle(
        db,
        _candle(high=2.4, close=2.0, volume=20, is_final=True),
        now=datetime(2026, 7, 26, 13, 1, tzinfo=timezone.utc),
    )

    assert updated == "UPDATED"
    assert finalized == "FINALIZED"
    assert existing.high_price == 2.4
    assert existing.close_price == 2.0
    assert existing.volume == 20
    assert existing.is_final is True
    assert existing.quality_state == "VERIFIED"
    assert existing.revision == 3
    assert db.commit.call_count == 2


def test_final_candle_is_immutable():
    existing = _existing()
    existing.is_final = True
    existing.quality_state = "VERIFIED"
    db = _db(existing=existing)

    status = MarketRepository().upsert_candle(
        db,
        _candle(high=9, close=8, is_final=True),
        now=datetime(2026, 7, 26, 13, 5, tzinfo=timezone.utc),
    )

    assert status == "UNCHANGED_FINAL"
    assert existing.high_price == 2.0
    assert existing.close_price == 1.5
    db.commit.assert_not_called()


def test_invalid_ohlc_is_rejected_before_query_or_write():
    db = _db(existing=None)

    status = MarketRepository().upsert_candle(
        db,
        _candle(high=1.0, low=2.0),
        now=NOW,
    )

    assert status == "REJECTED"
    db.query.assert_not_called()
    db.add.assert_not_called()
    db.commit.assert_not_called()


def _candle(
    *,
    high=2.0,
    low=0.5,
    close=1.5,
    volume=10.0,
    is_final=False,
):
    return {
        "symbol": "DOGEUSDT",
        "timeframe": "1h",
        "venue": "BINANCE",
        "market_type": "FUTURES",
        "source": "BINANCE_FUTURES_REST",
        "open_time_ms": OPEN_TIME_MS,
        "close_time_ms": CLOSE_TIME_MS,
        "is_final": is_final,
        "open": 1.0,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }


def _existing():
    return SimpleNamespace(
        symbol="DOGEUSDT",
        timeframe="1h",
        venue="BINANCE",
        market_type="FUTURES",
        open_price=1.0,
        high_price=2.0,
        low_price=0.5,
        close_price=1.5,
        volume=10.0,
        candle_time=datetime(2026, 7, 26, 12),
        open_time=datetime(2026, 7, 26, 12),
        close_time=datetime(2026, 7, 26, 13),
        is_final=False,
        source="BINANCE_FUTURES_REST",
        ingested_at=datetime(2026, 7, 26, 12, 1),
        updated_at=datetime(2026, 7, 26, 12, 1),
        revision=1,
        quality_state="PROVISIONAL",
    )


def _db(*, existing):
    query = Mock()
    query.filter.return_value = query
    query.first.return_value = existing
    return SimpleNamespace(
        query=Mock(return_value=query),
        add=Mock(),
        commit=Mock(),
        rollback=Mock(),
    )
