from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import backtest_api
from app.backtesting import walk_forward_jobs
from app.database.models.walk_forward_jobs import WalkForwardJob
from app.database.models.master_signals import MasterSignal
from app.database.models.point_in_time_snapshots import DecisionSnapshot
from app.database.models.symbols import Symbol
from app.database.sqlserver import Base
from app.jobs import walk_forward_queue_job
from app.jobs.walk_forward_queue_job import run_walk_forward_queue_job


def _client(monkeypatch, tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'walk_forward_jobs.sqlite').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine, tables=[WalkForwardJob.__table__])
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(walk_forward_jobs, "SessionLocal", factory)
    app = FastAPI()
    app.include_router(backtest_api.router)
    return TestClient(app)


def test_walk_forward_job_returns_immediately_and_polls_completed_result(
    monkeypatch,
    tmp_path,
):
    client = _client(monkeypatch, tmp_path)
    calls = []

    def fake_execute(**parameters):
        calls.append(parameters)
        return {"engine_version": "walk_forward_v1", "fold_count": 6}

    monkeypatch.setattr(backtest_api, "execute_walk_forward", fake_execute)
    monkeypatch.setattr(
        backtest_api,
        "build_phase2_validation_report",
        lambda result, **scope: {"overall_status": "PASS", "scope": scope},
    )
    monkeypatch.setattr(backtest_api, "_load_paper_measurement", lambda symbol: None)

    submitted = client.post(
        "/backtest/walk-forward/jobs",
        params={
            "symbol": "btcusdt",
            "signal": "LONG",
            "timeframe": "1h",
            "limit": 20,
            "train_size": 8,
            "test_size": 2,
            "step_size": 2,
            "min_train_trades": 1,
        },
    )

    assert submitted.status_code == 202
    job_id = submitted.json()["job_id"]
    completed = client.get(f"/backtest/walk-forward/jobs/{job_id}")
    assert completed.status_code == 200
    payload = completed.json()
    assert payload["status"] == "COMPLETED"
    assert payload["response"]["symbol"] == "BTCUSDT"
    assert payload["response"]["result"]["fold_count"] == 6
    assert payload["response"]["report"]["overall_status"] == "PASS"
    assert len(calls) == 1

    duplicate = client.post(
        "/backtest/walk-forward/jobs",
        params={
            "symbol": "btcusdt",
            "signal": "LONG",
            "timeframe": "1h",
            "limit": 20,
            "train_size": 8,
            "test_size": 2,
            "step_size": 2,
            "min_train_trades": 1,
        },
    )
    assert duplicate.status_code == 202
    assert duplicate.json()["job_id"] == job_id
    assert len(calls) == 1


def test_walk_forward_job_records_failure_without_timing_out_request(
    monkeypatch,
    tmp_path,
):
    client = _client(monkeypatch, tmp_path)

    def fail_execute(**_parameters):
        raise RuntimeError("synthetic replay failure")

    monkeypatch.setattr(backtest_api, "execute_walk_forward", fail_execute)

    submitted = client.post(
        "/backtest/walk-forward/jobs",
        params={
            "symbol": "ETHUSDT",
            "signal": "SHORT",
            "timeframe": "2h",
            "limit": 20,
            "train_size": 8,
            "test_size": 2,
            "step_size": 2,
        },
    )
    job_id = submitted.json()["job_id"]
    failed = client.get(f"/backtest/walk-forward/jobs/{job_id}")

    assert failed.status_code == 200
    assert failed.json()["status"] == "FAILED"
    assert "synthetic replay failure" in failed.json()["error"]
    assert failed.json()["response"] is None


def test_production_api_queues_replay_for_worker_instead_of_running_it(
    monkeypatch,
    tmp_path,
):
    client = _client(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(
        backtest_api,
        "get_settings",
        lambda: SimpleNamespace(process_role="api"),
    )
    monkeypatch.setattr(
        backtest_api,
        "execute_walk_forward",
        lambda **parameters: calls.append(parameters)
        or {"engine_version": "walk_forward_v1", "fold_count": 4},
    )
    monkeypatch.setattr(
        backtest_api,
        "build_phase2_validation_report",
        lambda result, **_scope: {"overall_status": "PASS"},
    )
    monkeypatch.setattr(backtest_api, "_load_paper_measurement", lambda _symbol: None)

    submitted = client.post(
        "/backtest/walk-forward/jobs",
        params={
            "symbol": "SOLUSDT",
            "signal": "LONG",
            "timeframe": "1h",
            "limit": 20,
            "train_size": 8,
            "test_size": 2,
            "step_size": 2,
        },
    )

    assert submitted.status_code == 202
    job_id = submitted.json()["job_id"]
    assert submitted.json()["status"] == "QUEUED"
    assert calls == []

    worker_result = run_walk_forward_queue_job()
    completed = client.get(f"/backtest/walk-forward/jobs/{job_id}").json()

    assert worker_result["status"] == "COMPLETED"
    assert worker_result["job_id"] == job_id
    assert completed["status"] == "COMPLETED"
    assert completed["response"]["result"]["fold_count"] == 4
    assert len(calls) == 1

    latest = client.get(
        "/backtest/walk-forward/latest",
        params={"symbol": "SOLUSDT", "signal": "LONG", "timeframe": "1h"},
    )
    assert latest.status_code == 200
    assert latest.json()["status"] == "COMPLETED"
    assert latest.json()["automatic"] is True
    assert latest.json()["response"]["result"]["fold_count"] == 4


def test_unknown_walk_forward_job_is_404(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    response = client.get("/backtest/walk-forward/jobs/not-a-valid-id")
    assert response.status_code == 404


def test_latest_automatic_scope_is_pending_before_first_worker_run(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)

    response = client.get(
        "/backtest/walk-forward/latest",
        params={"symbol": "DOGEUSDT", "signal": "SHORT", "timeframe": "4h"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "PENDING"
    assert response.json()["automatic"] is True
    assert response.json()["response"] is None


def test_automatic_scheduler_queues_fresh_directional_scope_once(monkeypatch, tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'automatic_walk_forward.sqlite').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(
        engine,
        tables=[
            Symbol.__table__,
            MasterSignal.__table__,
            DecisionSnapshot.__table__,
            WalkForwardJob.__table__,
        ],
    )
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(walk_forward_jobs, "SessionLocal", factory)
    monkeypatch.setattr(walk_forward_queue_job, "SessionLocal", factory)
    now = datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc)
    db = factory()
    try:
        db.add(Symbol(symbol="BNBUSDT", is_active=True))
        db.add(
            MasterSignal(
                symbol="BNBUSDT",
                timeframe="1h",
                signal="BUY",
                confidence=53,
                created_at=now.replace(tzinfo=None),
            )
        )
        db.commit()
    finally:
        db.close()

    first = walk_forward_queue_job._enqueue_next_automatic_walk_forward_job(now=now)
    duplicate = walk_forward_queue_job._enqueue_next_automatic_walk_forward_job(
        now=now + timedelta(minutes=1)
    )

    assert first["status"] == "QUEUED"
    assert first["parameters"]["symbol"] == "BNBUSDT"
    assert first["parameters"]["timeframe"] == "1h"
    assert first["parameters"]["signal"] == "LONG"
    assert duplicate is None
    engine.dispose()


def test_automatic_scheduler_prefers_current_governed_snapshot(monkeypatch, tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'automatic_snapshot.sqlite').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(
        engine,
        tables=[
            Symbol.__table__,
            MasterSignal.__table__,
            DecisionSnapshot.__table__,
            WalkForwardJob.__table__,
        ],
    )
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(walk_forward_jobs, "SessionLocal", factory)
    monkeypatch.setattr(walk_forward_queue_job, "SessionLocal", factory)
    now = datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc)
    db = factory()
    try:
        db.add(Symbol(symbol="ETHUSDT", is_active=True))
        db.add(
            MasterSignal(
                symbol="ETHUSDT",
                timeframe="1h",
                signal="BUY",
                confidence=80,
                created_at=now.replace(tzinfo=None),
            )
        )
        db.add(
            DecisionSnapshot(
                symbol="ETHUSDT",
                timeframe="2h",
                source_timestamp=now.replace(tzinfo=None),
                effective_timestamp=now.replace(tzinfo=None),
                feature_version="test",
                decision_version=walk_forward_queue_job.CORE_SIGNAL_DECISION_VERSION,
                strategy_id=walk_forward_queue_job.CORE_SIGNAL_STRATEGY_ID,
                strategy_version="test",
                quality_state="OK",
                decision="ELIGIBLE",
                confidence=55,
                snapshot_json='{"context":{"side":"SHORT"}}',
                created_at=now.replace(tzinfo=None),
            )
        )
        db.commit()
    finally:
        db.close()

    queued = walk_forward_queue_job._enqueue_next_automatic_walk_forward_job(now=now)

    assert queued["parameters"]["symbol"] == "ETHUSDT"
    assert queued["parameters"]["timeframe"] == "2h"
    assert queued["parameters"]["signal"] == "SHORT"
    engine.dispose()


def test_blocked_governed_snapshot_suppresses_legacy_signal(monkeypatch, tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'blocked_snapshot.sqlite').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(
        engine,
        tables=[
            Symbol.__table__,
            MasterSignal.__table__,
            DecisionSnapshot.__table__,
            WalkForwardJob.__table__,
        ],
    )
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(walk_forward_jobs, "SessionLocal", factory)
    monkeypatch.setattr(walk_forward_queue_job, "SessionLocal", factory)
    now = datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc)
    db = factory()
    try:
        db.add(Symbol(symbol="SOLUSDT", is_active=True))
        db.add(
            MasterSignal(
                symbol="SOLUSDT",
                timeframe="1h",
                signal="BUY",
                confidence=80,
                created_at=now.replace(tzinfo=None),
            )
        )
        db.add(
            DecisionSnapshot(
                symbol="SOLUSDT",
                timeframe="1h",
                source_timestamp=now.replace(tzinfo=None),
                effective_timestamp=now.replace(tzinfo=None),
                feature_version="test",
                decision_version=walk_forward_queue_job.CORE_SIGNAL_DECISION_VERSION,
                strategy_id=walk_forward_queue_job.CORE_SIGNAL_STRATEGY_ID,
                strategy_version="test",
                quality_state="OK",
                decision="BLOCKED",
                confidence=80,
                snapshot_json='{"context":{"side":"LONG"}}',
                created_at=now.replace(tzinfo=None),
            )
        )
        db.commit()
    finally:
        db.close()

    queued = walk_forward_queue_job._enqueue_next_automatic_walk_forward_job(now=now)

    assert queued is None
    engine.dispose()


def test_abandoned_queued_job_expires_with_retryable_error(monkeypatch, tmp_path):
    _client(monkeypatch, tmp_path)
    now = datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc)
    record, created = walk_forward_jobs.create_walk_forward_job(
        {"symbol": "BTCUSDT", "timeframe": "1h", "signal": "LONG"},
        now=now,
    )

    expired = walk_forward_jobs.expire_stale_walk_forward_job(
        record["job_id"],
        now=now + timedelta(seconds=121),
    )

    assert created is True
    assert expired["status"] == "FAILED"
    assert "abandoned while queued" in expired["error"]
    assert "Retry the validation" in expired["error"]

    retried, recreated = walk_forward_jobs.create_walk_forward_job(
        {"symbol": "BTCUSDT", "timeframe": "1h", "signal": "LONG"},
        now=now + timedelta(seconds=122),
    )
    assert recreated is True
    assert retried["job_id"] == record["job_id"]
    assert retried["status"] == "QUEUED"
    assert retried["error"] is None


def test_abandoned_running_job_expires_but_recent_job_does_not(monkeypatch, tmp_path):
    _client(monkeypatch, tmp_path)
    now = datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc)
    record, _ = walk_forward_jobs.create_walk_forward_job(
        {"symbol": "ETHUSDT", "timeframe": "2h", "signal": "SHORT"},
        now=now,
    )
    walk_forward_jobs.mark_walk_forward_job_running(record["job_id"], now=now)

    recent = walk_forward_jobs.expire_stale_walk_forward_job(
        record["job_id"],
        now=now + timedelta(minutes=19),
    )
    expired = walk_forward_jobs.expire_stale_walk_forward_job(
        record["job_id"],
        now=now + timedelta(minutes=21),
    )

    assert recent["status"] == "RUNNING"
    assert expired["status"] == "FAILED"
    assert "abandoned while running" in expired["error"]


def test_new_submission_purges_only_expired_terminal_jobs(monkeypatch, tmp_path):
    _client(monkeypatch, tmp_path)
    old = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)
    now = datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc)

    completed, _ = walk_forward_jobs.create_walk_forward_job(
        {"symbol": "BTCUSDT", "timeframe": "1h", "signal": "LONG"},
        now=old,
    )
    walk_forward_jobs.complete_walk_forward_job(
        completed["job_id"], {"result": "large"}, now=old
    )
    failed, _ = walk_forward_jobs.create_walk_forward_job(
        {"symbol": "ETHUSDT", "timeframe": "2h", "signal": "SHORT"},
        now=old + timedelta(minutes=5),
    )
    walk_forward_jobs.fail_walk_forward_job(failed["job_id"], "failed", now=old)
    running, _ = walk_forward_jobs.create_walk_forward_job(
        {"symbol": "XRPUSDT", "timeframe": "4h", "signal": "LONG"},
        now=old + timedelta(minutes=10),
    )
    walk_forward_jobs.mark_walk_forward_job_running(running["job_id"], now=old)

    current, created = walk_forward_jobs.create_walk_forward_job(
        {"symbol": "SOLUSDT", "timeframe": "1d", "signal": "SHORT"},
        now=now,
    )

    assert created is True
    assert walk_forward_jobs.load_walk_forward_job(completed["job_id"]) is None
    assert walk_forward_jobs.load_walk_forward_job(failed["job_id"]) is None
    assert walk_forward_jobs.load_walk_forward_job(running["job_id"])["status"] == "RUNNING"
    assert walk_forward_jobs.load_walk_forward_job(current["job_id"])["status"] == "QUEUED"


def test_synchronous_walk_forward_is_retired_without_executing(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    executed = []
    monkeypatch.setattr(
        backtest_api,
        "execute_walk_forward",
        lambda **parameters: executed.append(parameters),
    )

    response = client.get(
        "/backtest/walk-forward",
        params={"symbol": "BTCUSDT", "signal": "LONG", "timeframe": "1h"},
    )

    assert response.status_code == 410
    assert response.json()["detail"]["code"] == "SYNCHRONOUS_WALK_FORWARD_RETIRED"
    assert response.json()["detail"]["submit_url"] == "/api/backtest/walk-forward/jobs"
    assert executed == []


def test_synchronous_phase2_report_is_retired_without_executing(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    executed = []
    monkeypatch.setattr(
        backtest_api,
        "execute_walk_forward",
        lambda **parameters: executed.append(parameters),
    )

    response = client.get(
        "/backtest/phase2-report",
        params={"symbol": "BTCUSDT", "signal": "LONG", "timeframe": "1h"},
    )

    assert response.status_code == 410
    assert response.json()["detail"]["code"] == "SYNCHRONOUS_PHASE2_REPORT_RETIRED"
    assert response.json()["detail"]["submit_url"] == "/api/backtest/walk-forward/jobs"
    assert executed == []


def test_completed_job_persists_across_api_client_instances(monkeypatch, tmp_path):
    first = _client(monkeypatch, tmp_path)
    monkeypatch.setattr(
        backtest_api,
        "execute_walk_forward",
        lambda **_parameters: {"engine_version": "walk_forward_v1", "fold_count": 1},
    )
    monkeypatch.setattr(
        backtest_api,
        "build_phase2_validation_report",
        lambda result, **_scope: {"overall_status": "PASS"},
    )
    monkeypatch.setattr(backtest_api, "_load_paper_measurement", lambda _symbol: None)
    submitted = first.post(
        "/backtest/walk-forward/jobs",
        params={
            "symbol": "XRPUSDT",
            "signal": "SHORT",
            "timeframe": "4h",
            "limit": 20,
            "train_size": 8,
            "test_size": 2,
            "step_size": 2,
        },
    ).json()

    second = _client(monkeypatch, tmp_path)
    loaded = second.get(submitted["status_url"].removeprefix("/api"))

    assert loaded.status_code == 200
    assert loaded.json()["status"] == "COMPLETED"
    assert loaded.json()["response"]["result"]["fold_count"] == 1
