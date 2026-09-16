from datetime import datetime, timezone
from threading import Lock

from app.config import get_settings
from app.database.sqlserver import SessionLocal
from app.repositories.fast_exit_heartbeat_repository import FastExitHeartbeatRepository


EXIT_PROTECTION_MAX_AGE_SECONDS = 5

_lock = Lock()
_state = {
    "last_attempt_at": None,
    "last_success_at": None,
    "last_status": "NOT_STARTED",
    "last_duration_seconds": None,
    "last_error": None,
    "consecutive_failures": 0,
    "last_price_stream": None,
}


def record_exit_protection_run(summary, *, observed_at=None, persist=None):
    observed_at = _utc(observed_at or datetime.now(timezone.utc))
    summary = dict(summary or {})
    status = str(summary.get("status") or "FAILED").upper()
    errors = [str(item) for item in (summary.get("errors") or []) if item]
    missing = [str(item) for item in (summary.get("missing_prices") or []) if item]
    price_stream = summary.get("price_stream")
    price_stream = dict(price_stream) if isinstance(price_stream, dict) else None
    stream_ready = bool(price_stream and price_stream.get("ready") is True)
    healthy = status == "OK" and not errors and not missing and stream_ready
    error = None
    if not healthy:
        details = errors or (["Missing fresh marks: " + ", ".join(sorted(set(missing)))] if missing else [])
        if not stream_ready and not details:
            details = [
                (price_stream or {}).get("reason")
                or "Binance mark stream health was not reported"
            ]
        error = "; ".join(details) or f"Fast-exit worker status is {status}"

    with _lock:
        _state["last_attempt_at"] = observed_at
        _state["last_status"] = status
        _state["last_duration_seconds"] = _number_or_none(
            summary.get("duration_seconds")
        )
        _state["last_error"] = error
        _state["last_price_stream"] = price_stream
        if healthy:
            _state["last_success_at"] = observed_at
            _state["consecutive_failures"] = 0
        else:
            _state["consecutive_failures"] += 1
        state = _copy_state(_state)

    if _shared_storage_enabled(persist):
        try:
            _save_shared_state(state)
        except Exception as exc:
            # Exit evaluation remains useful if the heartbeat table is
            # temporarily unavailable. The API will fail closed when its
            # last shared heartbeat becomes stale.
            return _storage_failure_snapshot(
                observed_at,
                EXIT_PROTECTION_MAX_AGE_SECONDS,
                exc,
            )
    return _snapshot_from_state(state, now=observed_at)


def exit_protection_snapshot(*, now=None, max_age_seconds=None, shared=None):
    now = _utc(now or datetime.now(timezone.utc))
    max_age = float(
        EXIT_PROTECTION_MAX_AGE_SECONDS
        if max_age_seconds is None
        else max_age_seconds
    )
    if _shared_storage_enabled(shared):
        try:
            state = _load_shared_state() or _initial_state()
        except Exception as exc:
            return _storage_failure_snapshot(now, max_age, exc)
    else:
        with _lock:
            state = _copy_state(_state)

    return _snapshot_from_state(state, now=now, max_age=max_age)


def _snapshot_from_state(state, *, now, max_age=None):
    now = _utc(now)
    max_age = float(EXIT_PROTECTION_MAX_AGE_SECONDS if max_age is None else max_age)

    last_attempt = (
        _utc(state["last_attempt_at"])
        if state.get("last_attempt_at") is not None
        else None
    )
    last_success = (
        _utc(state["last_success_at"])
        if state.get("last_success_at") is not None
        else None
    )
    age_seconds = (
        max(0.0, (now - last_success).total_seconds())
        if last_success is not None
        else None
    )
    fresh = age_seconds is not None and age_seconds <= max_age
    ready = state["last_status"] == "OK" and fresh and not state["last_error"]
    if last_attempt is None:
        reason = "One-second exit protection has not completed its first run"
    elif state["last_status"] != "OK" or state["last_error"]:
        reason = state["last_error"] or "One-second exit protection is degraded"
    elif not fresh:
        reason = (
            f"One-second exit protection heartbeat is stale "
            f"({age_seconds:.2f}s old; limit {max_age:.2f}s)"
        )
    else:
        reason = None

    return {
        "policy": "FAST_EXIT_SHARED_STREAM_HEARTBEAT_V3",
        "ready": ready,
        "status": "READY" if ready else "BLOCKED",
        "reason": reason,
        "max_age_seconds": max_age,
        "age_seconds": round(age_seconds, 3) if age_seconds is not None else None,
        "last_attempt_at": _iso(last_attempt),
        "last_success_at": _iso(last_success),
        "last_worker_status": state["last_status"],
        "last_duration_seconds": state["last_duration_seconds"],
        "last_error": state["last_error"],
        "consecutive_failures": state["consecutive_failures"],
        "price_stream": state["last_price_stream"],
    }


def _shared_storage_enabled(override):
    if override is not None:
        return bool(override)
    return get_settings().process_role in {"api", "worker"}


def _save_shared_state(state):
    db = SessionLocal()
    try:
        FastExitHeartbeatRepository().save(db, state)
    finally:
        db.close()


def _load_shared_state():
    db = SessionLocal()
    try:
        return FastExitHeartbeatRepository().load(db)
    finally:
        db.close()


def _storage_failure_snapshot(now, max_age, exc):
    error = f"Shared exit-protection heartbeat is unavailable: {type(exc).__name__}"
    return {
        "policy": "FAST_EXIT_SHARED_STREAM_HEARTBEAT_V3",
        "ready": False,
        "status": "BLOCKED",
        "reason": error,
        "max_age_seconds": max_age,
        "age_seconds": None,
        "last_attempt_at": None,
        "last_success_at": None,
        "last_worker_status": "STORAGE_UNAVAILABLE",
        "last_duration_seconds": None,
        "last_error": error,
        "consecutive_failures": 0,
        "price_stream": None,
    }


def reset_exit_protection_health():
    """Reset process-local state; intended for deterministic tests only."""

    with _lock:
        _state.update(
            {
                "last_attempt_at": None,
                "last_success_at": None,
                "last_status": "NOT_STARTED",
                "last_duration_seconds": None,
                "last_error": None,
                "consecutive_failures": 0,
                "last_price_stream": None,
            }
        )


def _initial_state():
    return {
        "last_attempt_at": None,
        "last_success_at": None,
        "last_status": "NOT_STARTED",
        "last_duration_seconds": None,
        "last_error": None,
        "consecutive_failures": 0,
        "last_price_stream": None,
    }


def _copy_state(state):
    result = dict(state)
    if isinstance(result.get("last_price_stream"), dict):
        result["last_price_stream"] = dict(result["last_price_stream"])
    return result


def _utc(value):
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value):
    return value.isoformat() if value is not None else None


def _number_or_none(value):
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None
