from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import backtest_api
from app.backtesting import walk_forward_jobs
from app.database.models.walk_forward_jobs import WalkForwardJob
from app.database.sqlserver import Base


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


def test_unknown_walk_forward_job_is_404(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    response = client.get("/backtest/walk-forward/jobs/not-a-valid-id")
    assert response.status_code == 404


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
