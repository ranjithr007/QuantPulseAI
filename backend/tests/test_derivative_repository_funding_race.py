from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

from sqlalchemy.exc import IntegrityError

from app.repositories.derivative_repository import DerivativeRepository


def test_save_funding_recovers_when_another_worker_wins_insert_race():
    canonical = SimpleNamespace(rate=0.0001)
    query = Mock()
    query.filter.return_value.first.side_effect = [None, canonical]
    db = Mock()
    db.query.return_value = query
    db.commit.side_effect = [
        IntegrityError("insert", {}, Exception("duplicate")),
        None,
    ]
    event = {
        "symbol": "bnbusdt",
        "rate": 0.0002,
        "time": datetime(2026, 9, 6, 21, 30),
    }

    result = DerivativeRepository().save_funding(db, event)

    assert result is canonical
    assert canonical.rate == 0.0002
    assert db.rollback.call_count == 1
    assert db.commit.call_count == 2


def test_save_funding_accepts_duplicate_before_winner_is_visible():
    query = Mock()
    query.filter.return_value.first.return_value = None
    db = Mock()
    db.query.return_value = query
    db.commit.side_effect = IntegrityError(
        "insert",
        {},
        Exception("duplicate key uq_funding_rates_symbol_event"),
    )

    result = DerivativeRepository().save_funding(
        db,
        {
            "symbol": "BNBUSDT",
            "rate": 0.0002,
            "time": datetime(2026, 9, 13, 5, 30),
        },
    )

    assert result is None
    assert db.rollback.call_count == 1
