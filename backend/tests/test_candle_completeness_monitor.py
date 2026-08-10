from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.jobs import candle_completeness_job
from app.observability.candle_completeness import (
    build_candle_completeness_report,
)
from app.scheduler.registry import get_job_definition


CUTOFF = datetime(2026, 7, 27, 15, tzinfo=timezone.utc)


def _candles(count, *, missing_index=None):
    records = []
    for index in range(1, count + 1):
        if index == missing_index:
            continue
        open_time = CUTOFF + timedelta(hours=index)
        records.append(
            SimpleNamespace(
                open_time=open_time,
                candle_time=open_time,
                close_time=open_time + timedelta(hours=1),
                is_final=True,
            )
        )
    return records


def test_monitor_reports_progress_floor_and_gap():
    data = {
        "BTCUSDT": _candles(10),
        "ETHUSDT": _candles(10, missing_index=5),
    }

    report = build_candle_completeness_report(
        object(),
        symbols=("BTCUSDT", "ETHUSDT"),
        timeframes=("1h",),
        now=CUTOFF + timedelta(hours=11),
        candle_loader=lambda _db, symbol, _timeframe, _now, limit: data[symbol],
    )

    assert report["status"] == "DEGRADED"
    assert report["temporal_validation"]["safe_completed_1h_candles"] == 9
    assert report["temporal_validation"]["remaining_1h_candles"] == 1431
    assert report["series"]["ETHUSDT:1h"]["missing_after_cutoff"] == 1
    assert "WINDOW_GAPS" in report["series"]["ETHUSDT:1h"]["issues"]


def test_monitor_is_healthy_when_collection_is_contiguous_and_fresh():
    report = build_candle_completeness_report(
        object(),
        symbols=("BTCUSDT",),
        timeframes=("1h",),
        now=CUTOFF + timedelta(hours=11),
        candle_loader=lambda *_args, **_kwargs: _candles(10),
    )

    assert report["status"] == "HEALTHY"
    assert report["series"]["BTCUSDT:1h"]["latest_age_seconds"] == 0
    assert report["temporal_validation"]["progress_percent"] == 0.69


def test_job_contains_failure_and_closes_session(monkeypatch):
    session = SimpleNamespace(close=lambda: None)
    closed = {"value": False}
    session.close = lambda: closed.update(value=True)
    monkeypatch.setattr(candle_completeness_job, "SessionLocal", lambda: session)
    monkeypatch.setattr(candle_completeness_job, "_prepare_storage", lambda: None)
    monkeypatch.setattr(
        candle_completeness_job,
        "build_candle_completeness_report",
        lambda _db: (_ for _ in ()).throw(RuntimeError("db unavailable")),
    )

    result = candle_completeness_job.run_candle_completeness_job()

    assert result["status"] == "FAILED"
    assert result["reason"] == "db unavailable"
    assert closed["value"] is True


def test_monitor_is_registered_every_fifteen_minutes():
    definition = get_job_definition("candle_completeness")

    assert definition.function == "run_candle_completeness_job"
    assert definition.minutes == 15
    assert definition.coalesce is True
