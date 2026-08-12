import hashlib
import json
import re
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError

from app.database.models.walk_forward_jobs import WalkForwardJob
from app.database.sqlserver import SessionLocal
from app.repositories._db_utils import commit_or_rollback


JOB_VERSION = "walk_forward_job_v2_database"
JOB_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")


def create_walk_forward_job(parameters, *, now=None):
    created_at = _utc_now(now)
    job_id = _job_id(parameters, created_at)
    db = SessionLocal()
    try:
        existing = db.get(WalkForwardJob, job_id)
        if existing is not None and existing.status != "FAILED":
            return _record(existing), False
        if existing is None:
            existing = WalkForwardJob(job_id=job_id)
            db.add(existing)
        existing.source = JOB_VERSION
        existing.status = "QUEUED"
        existing.created_at = _db_timestamp(created_at)
        existing.started_at = None
        existing.completed_at = None
        existing.parameters_json = _json(parameters)
        existing.response_json = None
        existing.error_message = None
        try:
            commit_or_rollback(db)
        except IntegrityError:
            db.rollback()
            concurrent = db.get(WalkForwardJob, job_id)
            if concurrent is None:
                raise
            return _record(concurrent), False
        db.refresh(existing)
        return _record(existing), True
    finally:
        db.close()


def mark_walk_forward_job_running(job_id, *, now=None):
    return _update_job(
        job_id,
        status="RUNNING",
        started_at=_db_timestamp(_utc_now(now)),
        completed_at=None,
        error_message=None,
    )


def complete_walk_forward_job(job_id, response, *, now=None):
    return _update_job(
        job_id,
        status="COMPLETED",
        completed_at=_db_timestamp(_utc_now(now)),
        response_json=_json(response),
        error_message=None,
    )


def fail_walk_forward_job(job_id, error, *, now=None):
    message = str(error or "Walk-forward job failed").strip()
    return _update_job(
        job_id,
        status="FAILED",
        completed_at=_db_timestamp(_utc_now(now)),
        response_json=None,
        error_message=message[:2000],
    )


def load_walk_forward_job(job_id):
    normalized = _validated_job_id(job_id)
    db = SessionLocal()
    try:
        record = db.get(WalkForwardJob, normalized)
        return _record(record) if record is not None else None
    finally:
        db.close()


def public_walk_forward_job(record):
    if record is None:
        return None
    job_id = record.get("job_id")
    return {
        "source": record.get("source") or JOB_VERSION,
        "job_id": job_id,
        "status": record.get("status"),
        "status_url": f"/api/backtest/walk-forward/jobs/{job_id}",
        "created_at": record.get("created_at"),
        "started_at": record.get("started_at"),
        "completed_at": record.get("completed_at"),
        "response": record.get("response"),
        "error": record.get("error"),
    }


def _update_job(job_id, **changes):
    normalized = _validated_job_id(job_id)
    db = SessionLocal()
    try:
        record = db.get(WalkForwardJob, normalized)
        if record is None:
            raise FileNotFoundError(f"Unknown walk-forward job: {normalized}")
        for name, value in changes.items():
            setattr(record, name, value)
        commit_or_rollback(db)
        db.refresh(record)
        return _record(record)
    finally:
        db.close()


def _record(record):
    return {
        "source": record.source,
        "job_id": record.job_id,
        "status": record.status,
        "created_at": _iso_utc(record.created_at),
        "started_at": _iso_utc(record.started_at),
        "completed_at": _iso_utc(record.completed_at),
        "parameters": _load_json(record.parameters_json, {}),
        "response": _load_json(record.response_json, None),
        "error": record.error_message,
    }


def _job_id(parameters, created_at):
    # One five-minute bucket deduplicates concurrent dashboard consumers while
    # allowing a later candle refresh to request a new validation run.
    bucket = int(created_at.timestamp()) // 300
    canonical = json.dumps(parameters, sort_keys=True, default=_json_default)
    digest = hashlib.sha256(f"{JOB_VERSION}:{bucket}:{canonical}".encode("utf-8"))
    return digest.hexdigest()[:32]


def _validated_job_id(job_id):
    normalized = str(job_id or "").strip().lower()
    if not JOB_ID_PATTERN.fullmatch(normalized):
        raise ValueError("Invalid walk-forward job id")
    return normalized


def _json(value):
    return json.dumps(value, sort_keys=True, default=_json_default)


def _load_json(value, default):
    if value is None:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _utc_now(value=None):
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        return current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _db_timestamp(value):
    return _utc_now(value).replace(tzinfo=None)


def _iso_utc(value):
    if value is None:
        return None
    current = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat()


def _json_default(value):
    if isinstance(value, datetime):
        return _utc_now(value).isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")

