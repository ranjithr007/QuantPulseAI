import hashlib
import json
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.exc import SQLAlchemyError

from app.database.models.walk_forward_jobs import WalkForwardJob
from app.database.sqlserver import SessionLocal
from app.governance.evidence_policy import govern_phase2_report
from app.repositories._db_utils import commit_or_rollback


JOB_VERSION = "walk_forward_job_v2_database"
JOB_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")
QUEUED_STALE_AFTER_SECONDS = 120
RUNNING_STALE_AFTER_SECONDS = 20 * 60
JOB_RETENTION_DAYS = 14
JOB_RETENTION_BATCH_SIZE = 100


def create_walk_forward_job(parameters, *, now=None):
    created_at = _utc_now(now)
    job_id = _job_id(parameters, created_at)
    db = SessionLocal()
    try:
        existing = db.get(WalkForwardJob, job_id)
        if existing is not None and existing.status != "FAILED":
            stale_reason = _stale_job_reason(existing, created_at)
            if stale_reason is None:
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
        created_record = _record(existing)
        try:
            _purge_expired_jobs(db, created_at)
            commit_or_rollback(db)
        except SQLAlchemyError:
            # Retention is best-effort and must never prevent a validation from
            # being submitted after the job itself has committed successfully.
            db.rollback()
        return created_record, True
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


def load_latest_walk_forward_job(symbol, timeframe, signal):
    """Return the newest durable validation for one governed scope."""

    normalized_scope = (
        str(symbol or "").strip().upper(),
        str(timeframe or "").strip().lower(),
        str(signal or "").strip().upper(),
    )
    db = SessionLocal()
    try:
        rows = (
            db.query(WalkForwardJob)
            .filter(
                WalkForwardJob.parameters_json.contains(
                    f'"symbol": {json.dumps(normalized_scope[0])}'
                ),
                WalkForwardJob.parameters_json.contains(
                    f'"timeframe": {json.dumps(normalized_scope[1])}'
                ),
                WalkForwardJob.parameters_json.contains(
                    f'"signal": {json.dumps(normalized_scope[2])}'
                ),
            )
            .order_by(WalkForwardJob.created_at.desc(), WalkForwardJob.job_id.desc())
            .limit(20)
            .all()
        )
        for row in rows:
            parameters = _load_json(row.parameters_json, {})
            scope = (
                str(parameters.get("symbol") or "").strip().upper(),
                str(parameters.get("timeframe") or "").strip().lower(),
                str(parameters.get("signal") or "").strip().upper(),
            )
            if scope == normalized_scope:
                return _record(row)
        return None
    finally:
        db.close()


def summarize_completed_walk_forward_jobs(
    *,
    symbol=None,
    timeframe=None,
    signal=None,
    limit=20,
):
    """Summarize durable automatic results across governed scopes.

    Automatic validation runs in a separate Railway worker, so filesystem
    artifacts written by that process are not visible to the API service.
    Completed job responses live in the shared database and are therefore the
    authoritative source for the automatic cross-scope view.
    """

    normalized_symbol = str(symbol or "").strip().upper()
    normalized_timeframe = str(timeframe or "").strip().lower()
    normalized_signal = str(signal or "").strip().upper()
    record_limit = max(1, int(limit))
    # Keep this endpoint light: response_json also contains the full replay,
    # while the UI only needs the two newest reports per scope for drift.
    scan_limit = max(50, min(200, record_limit * 5))

    db = SessionLocal()
    try:
        query = db.query(WalkForwardJob).filter(
            WalkForwardJob.status == "COMPLETED",
            WalkForwardJob.response_json.isnot(None),
        )
        if normalized_symbol:
            query = query.filter(
                WalkForwardJob.parameters_json.contains(
                    f'"symbol": {json.dumps(normalized_symbol)}'
                )
            )
        if normalized_timeframe:
            query = query.filter(
                WalkForwardJob.parameters_json.contains(
                    f'"timeframe": {json.dumps(normalized_timeframe)}'
                )
            )
        if normalized_signal:
            query = query.filter(
                WalkForwardJob.parameters_json.contains(
                    f'"signal": {json.dumps(normalized_signal)}'
                )
            )
        rows = (
            query.order_by(
                WalkForwardJob.completed_at.desc(),
                WalkForwardJob.created_at.desc(),
                WalkForwardJob.job_id.desc(),
            )
            .limit(scan_limit)
            .all()
        )
    finally:
        db.close()

    grouped = {}
    for row in rows:
        parameters = _load_json(row.parameters_json, {})
        response = _load_json(row.response_json, {})
        scope = {
            "symbol": str(
                response.get("symbol") or parameters.get("symbol") or ""
            ).strip().upper(),
            "timeframe": str(
                response.get("timeframe") or parameters.get("timeframe") or ""
            ).strip().lower(),
            "signal": str(
                response.get("signal") or parameters.get("signal") or ""
            ).strip().upper(),
        }
        if normalized_symbol and scope["symbol"] != normalized_symbol:
            continue
        if normalized_timeframe and scope["timeframe"] != normalized_timeframe:
            continue
        if normalized_signal and scope["signal"] != normalized_signal:
            continue
        if not all(scope.values()):
            continue
        saved_at = _iso_utc(row.completed_at or row.created_at)
        raw_report = response.get("report")
        if not isinstance(raw_report, dict) or not raw_report:
            continue
        report = govern_phase2_report(
            raw_report,
            recorded_at=saved_at,
        )
        grouped.setdefault(
            (scope["symbol"], scope["timeframe"], scope["signal"]),
            [],
        ).append(
            {
                "job_id": row.job_id,
                "saved_at": saved_at,
                "scope": scope,
                "report": report,
            }
        )

    records = []
    for items in grouped.values():
        latest = items[0]
        previous = items[1] if len(items) > 1 else None
        records.append(
            _walk_forward_scope_summary_record(latest, previous, len(items))
        )
    records.sort(key=lambda item: item.get("saved_at") or "", reverse=True)
    return records[:record_limit]


def create_automatic_walk_forward_job(
    parameters,
    *,
    refresh_after_seconds,
    now=None,
):
    """Queue a scope only when its last automatic validation is due.

    A queued/running job is always reused. Completed jobs are reused for the
    configured cadence, preventing the ten-second worker poll from creating a
    replay backlog.
    """

    checked_at = _utc_now(now)
    canonical = _json(parameters)
    db = SessionLocal()
    try:
        latest = (
            db.query(WalkForwardJob)
            .filter(WalkForwardJob.parameters_json == canonical)
            .order_by(WalkForwardJob.created_at.desc(), WalkForwardJob.job_id.desc())
            .first()
        )
        if latest is not None:
            stale_reason = _stale_job_reason(latest, checked_at)
            if stale_reason is not None:
                latest.status = "FAILED"
                latest.completed_at = _db_timestamp(checked_at)
                latest.response_json = None
                latest.error_message = stale_reason
                commit_or_rollback(db)
            elif str(latest.status or "").upper() in {"QUEUED", "RUNNING"}:
                return _record(latest), False
            elif str(latest.status or "").upper() == "COMPLETED":
                anchor = latest.completed_at or latest.created_at
                age_seconds = max(
                    0.0,
                    (checked_at - _utc_now(anchor)).total_seconds(),
                )
                if age_seconds < max(1, int(refresh_after_seconds)):
                    return _record(latest), False
    finally:
        db.close()

    return create_walk_forward_job(parameters, now=checked_at)


def claim_next_walk_forward_job(*, now=None):
    """Atomically reserve the oldest queued replay for one worker process."""

    claimed_at = _utc_now(now)
    db = SessionLocal()
    try:
        query = (
            db.query(WalkForwardJob)
            .filter(WalkForwardJob.status == "QUEUED")
            .order_by(WalkForwardJob.created_at.asc(), WalkForwardJob.job_id.asc())
        )
        dialect = str(getattr(getattr(db.get_bind(), "dialect", None), "name", ""))
        if dialect == "postgresql":
            query = query.with_for_update(skip_locked=True)
        record = query.first()
        if record is None:
            return None
        record.status = "RUNNING"
        record.started_at = _db_timestamp(claimed_at)
        record.completed_at = None
        record.error_message = None
        commit_or_rollback(db)
        db.refresh(record)
        return _record(record)
    finally:
        db.close()


def expire_stale_walk_forward_job(job_id, *, now=None):
    """Fail an abandoned job so clients can retry after a process restart."""

    normalized = _validated_job_id(job_id)
    checked_at = _utc_now(now)
    db = SessionLocal()
    try:
        record = db.get(WalkForwardJob, normalized)
        if record is None:
            return None
        stale_reason = _stale_job_reason(record, checked_at)
        if stale_reason is not None:
            record.status = "FAILED"
            record.completed_at = _db_timestamp(checked_at)
            record.response_json = None
            record.error_message = stale_reason
            commit_or_rollback(db)
            db.refresh(record)
        return _record(record)
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


def _walk_forward_scope_summary_record(latest, previous, sample_count):
    latest_report = dict(latest.get("report") or {})
    previous_report = dict((previous or {}).get("report") or {})
    latest_metrics = dict(latest_report.get("derived_metrics") or {})
    previous_metrics = dict(previous_report.get("derived_metrics") or {})
    job_id = latest.get("job_id")
    return {
        "artifact_id": f"automatic_{job_id}",
        "job_id": job_id,
        "source": "automatic_walk_forward_database_v1",
        "saved_at": latest.get("saved_at"),
        "scope": dict(latest.get("scope") or {}),
        "overall_status": latest_report.get("overall_status"),
        "architecture_gate_status": dict(
            latest_report.get("architecture_gate") or {}
        ).get("status"),
        "evidence_status": latest_report.get("evidence_status"),
        "promotion_allowed": latest_report.get("promotion_allowed", False),
        "promotion_status": latest_report.get("promotion_status", "BLOCKED_R0"),
        "json_path": None,
        "markdown_path": None,
        "exists": True,
        "sample_count": int(sample_count),
        "previous_saved_at": previous.get("saved_at") if previous else None,
        "status_change": _walk_forward_status_change(
            latest_report.get("overall_status"),
            previous_report.get("overall_status"),
        ),
        "drift": {
            name: _walk_forward_delta(
                latest_metrics.get(name),
                previous_metrics.get(name),
            )
            for name in (
                "out_of_sample_total_return_percent",
                "out_of_sample_profit_factor",
                "out_of_sample_win_rate",
                "out_of_sample_max_drawdown_percent",
                "out_of_sample_payoff_ratio",
            )
        },
        "latest_metrics": latest_metrics,
        "previous_metrics": previous_metrics if previous else None,
    }


def _walk_forward_delta(current, previous):
    try:
        if current is None or previous is None:
            return None
        return round(float(current) - float(previous), 4)
    except (TypeError, ValueError):
        return None


def _walk_forward_status_change(current, previous):
    current_value = str(current or "")
    previous_value = str(previous or "")
    if not previous_value:
        return "FIRST_SAMPLE"
    if current_value == previous_value:
        return "UNCHANGED"
    return f"{previous_value}_TO_{current_value}"


def _stale_job_reason(record, now):
    status = str(getattr(record, "status", "") or "").upper()
    if status == "QUEUED":
        anchor = getattr(record, "created_at", None)
        threshold = QUEUED_STALE_AFTER_SECONDS
        label = "queued"
    elif status == "RUNNING":
        anchor = getattr(record, "started_at", None) or getattr(
            record, "created_at", None
        )
        threshold = RUNNING_STALE_AFTER_SECONDS
        label = "running"
    else:
        return None
    if anchor is None:
        return f"Walk-forward job was abandoned while {label}; retry the validation."

    age_seconds = max(0.0, (_utc_now(now) - _utc_now(anchor)).total_seconds())
    if age_seconds <= threshold:
        return None
    return (
        f"Walk-forward job was abandoned while {label} for "
        f"{int(age_seconds)} seconds, likely because the process restarted. "
        "Retry the validation."
    )


def _purge_expired_jobs(db, now):
    cutoff = _db_timestamp(_utc_now(now) - timedelta(days=JOB_RETENTION_DAYS))
    expired_ids = [
        job_id
        for (job_id,) in (
            db.query(WalkForwardJob.job_id)
            .filter(WalkForwardJob.status.in_(["COMPLETED", "FAILED"]))
            .filter(WalkForwardJob.completed_at.isnot(None))
            .filter(WalkForwardJob.completed_at < cutoff)
            .order_by(WalkForwardJob.completed_at.asc(), WalkForwardJob.job_id.asc())
            .limit(JOB_RETENTION_BATCH_SIZE)
            .all()
        )
    ]
    if not expired_ids:
        return 0
    return (
        db.query(WalkForwardJob)
        .filter(WalkForwardJob.job_id.in_(expired_ids))
        .delete(synchronize_session=False)
    )


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

