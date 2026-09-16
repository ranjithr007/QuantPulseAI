from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1.paper_trade_api import _exit_protection_blockers
from app.paper_trading.exit_protection_health import exit_protection_snapshot
from app.paper_trading.exit_protection_health import record_exit_protection_run
from app.paper_trading.exit_protection_health import reset_exit_protection_health
from app.database.sqlserver import Base
from app.database.paper_execution_schema import ensure_paper_execution_schema
from app.paper_trading import exit_protection_health as health_module


def ready_stream():
    return {
        "policy": "BINANCE_MARK_STREAM_HEALTH_V1",
        "ready": True,
        "connected": True,
        "reason": None,
        "max_age_seconds": 5.0,
        "message_age_seconds": 0.1,
        "last_message_at": "2026-09-13T12:00:00+00:00",
        "last_error": None,
        "thread_alive": True,
    }


@pytest.fixture(autouse=True)
def _fresh_health_state():
    reset_exit_protection_health()
    yield
    reset_exit_protection_health()


def test_exit_protection_is_blocked_until_first_successful_run():
    snapshot = exit_protection_snapshot()

    assert snapshot["ready"] is False
    assert snapshot["last_worker_status"] == "NOT_STARTED"
    assert "first run" in snapshot["reason"]
    assert _exit_protection_blockers(snapshot) == [snapshot["reason"]]


def test_recent_success_is_ready_and_then_becomes_stale():
    observed_at = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)
    record_exit_protection_run(
        {"status": "OK", "duration_seconds": 0.12, "price_stream": ready_stream()},
        observed_at=observed_at,
    )

    fresh = exit_protection_snapshot(
        now=observed_at + timedelta(seconds=4.9)
    )
    stale = exit_protection_snapshot(
        now=observed_at + timedelta(seconds=5.1)
    )

    assert fresh["ready"] is True
    assert fresh["price_stream"]["connected"] is True
    assert _exit_protection_blockers(fresh) == []
    assert stale["ready"] is False
    assert "stale" in stale["reason"]


def test_degraded_run_blocks_even_when_a_previous_success_is_fresh():
    observed_at = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)
    record_exit_protection_run(
        {"status": "OK", "duration_seconds": 0.1, "price_stream": ready_stream()},
        observed_at=observed_at,
    )
    record_exit_protection_run(
        {
            "status": "DEGRADED",
            "duration_seconds": 0.2,
            "missing_prices": ["ETHUSDT"],
        },
        observed_at=observed_at + timedelta(seconds=1),
    )

    snapshot = exit_protection_snapshot(
        now=observed_at + timedelta(seconds=2)
    )

    assert snapshot["ready"] is False
    assert snapshot["last_worker_status"] == "DEGRADED"
    assert snapshot["consecutive_failures"] == 1
    assert "ETHUSDT" in snapshot["reason"]


def test_worker_success_without_stream_proof_is_blocked():
    observed_at = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)
    record_exit_protection_run(
        {"status": "OK", "duration_seconds": 0.1},
        observed_at=observed_at,
    )

    snapshot = exit_protection_snapshot(now=observed_at)

    assert snapshot["ready"] is False
    assert "health was not reported" in snapshot["reason"]


def test_worker_heartbeat_is_visible_to_a_separate_api_process(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    ensure_paper_execution_schema(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(health_module, "SessionLocal", factory)
    observed_at = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)

    record_exit_protection_run(
        {"status": "OK", "duration_seconds": 0.1, "price_stream": ready_stream()},
        observed_at=observed_at,
        persist=True,
    )
    reset_exit_protection_health()  # Simulate the API's separate process memory.
    snapshot = exit_protection_snapshot(now=observed_at, shared=True)

    assert snapshot["policy"] == "FAST_EXIT_SHARED_STREAM_HEARTBEAT_V3"
    assert snapshot["ready"] is True
    assert snapshot["price_stream"]["connected"] is True
    engine.dispose()


def test_shared_heartbeat_storage_failure_blocks_entries(monkeypatch):
    monkeypatch.setattr(
        health_module,
        "SessionLocal",
        lambda: (_ for _ in ()).throw(RuntimeError("database unavailable")),
    )

    snapshot = exit_protection_snapshot(shared=True)

    assert snapshot["ready"] is False
    assert snapshot["last_worker_status"] == "STORAGE_UNAVAILABLE"
    assert _exit_protection_blockers(snapshot) == [snapshot["reason"]]
