from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import get_settings
from app.database.runtime import DATABASE_URL
from app.database.runtime import USING_SQLITE_FALLBACK
from app.database.runtime import engine
from app.database.runtime import SessionLocal
from app.repositories.pipeline_run_repository import PipelineRunRepository
from app.contracts.health import DependencyHealthResponse
from app.contracts.health import ExitProtectionHealth
from app.contracts.health import HealthResponse
from app.contracts.health import PipelineHealthResponse
from app.jobs.candle_completeness_job import run_candle_completeness_job
from app.observability.candle_completeness import (
    get_cached_candle_completeness_report,
)
from app.observability.database_storage import build_database_storage_report
from app.paper_trading.exit_protection_health import exit_protection_snapshot


PIPELINE_REQUIRED_STAGES = (
    "market",
    "feature",
    "regime",
    "orderflow",
    "smc",
    "fusion",
    "watchlist_persist",
    "risk",
)


router = APIRouter(prefix="/health", tags=["Health"])


@router.get("", response_model=HealthResponse)
async def health():
    settings = get_settings()

    return {
        "system": settings.app_name,
        "version": settings.version,
        "environment": settings.environment,
        "status": "running",
        "scheduler_enabled": settings.run_scheduler,
        "process_role": settings.process_role,
        "admin_auth_required": settings.require_admin_auth,
    }


@router.get("/live")
async def liveness_probe():
    settings = get_settings()
    return {
        "status": "alive",
        "process_role": settings.process_role,
    }


@router.get("/ready")
def readiness_probe():
    settings = get_settings()
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(
            {
                "status": "not_ready",
                "process_role": settings.process_role,
                "reason": "DATABASE_UNAVAILABLE",
            },
            status_code=503,
        )
    finally:
        db.close()

    if settings.environment == "production" and USING_SQLITE_FALLBACK:
        return JSONResponse(
            {
                "status": "not_ready",
                "process_role": settings.process_role,
                "reason": "NON_CANONICAL_EVIDENCE_STORAGE",
            },
            status_code=503,
        )

    return {
        "status": "ready",
        "process_role": settings.process_role,
        "evidence_storage": _evidence_storage(),
    }


@router.get("/dependencies", response_model=DependencyHealthResponse)
async def dependency_check():
    return {
        "database_configured": bool(DATABASE_URL),
        "database_url_scheme": DATABASE_URL.split("://", 1)[0] if "://" in DATABASE_URL else "unknown",
        "active_database_scheme": engine.url.get_backend_name(),
        "using_sqlite_fallback": USING_SQLITE_FALLBACK,
        "evidence_storage": _evidence_storage(),
        "database_pool": _database_pool_status(),
    }


def _evidence_storage():
    if USING_SQLITE_FALLBACK:
        return "SQLITE_FALLBACK"
    backend = engine.url.get_backend_name()
    if backend == "mssql":
        return "SQL_SERVER"
    if backend == "postgresql":
        return "POSTGRESQL"
    return backend.upper()


def _database_pool_status():
    settings = get_settings()
    pool = engine.pool
    configured_size = settings.database_pool_size
    configured_max_overflow = settings.database_max_overflow
    capacity = configured_size + configured_max_overflow
    checked_in = _pool_metric(pool, "checkedin")
    checked_out = _pool_metric(pool, "checkedout")
    raw_overflow = _pool_metric(pool, "overflow")
    overflow_in_use = max(0, raw_overflow) if raw_overflow is not None else None
    utilization = (
        round((checked_out / capacity) * 100, 2)
        if checked_out is not None and capacity > 0
        else None
    )

    return {
        "implementation": type(pool).__name__,
        "configured_size": configured_size,
        "configured_max_overflow": configured_max_overflow,
        "capacity": capacity,
        "checked_in": checked_in,
        "checked_out": checked_out,
        "overflow_in_use": overflow_in_use,
        "utilization_percent": utilization,
        "status": "SATURATED" if checked_out is not None and checked_out >= capacity else "NORMAL",
    }


def _pool_metric(pool, name):
    metric = getattr(pool, name, None)
    if not callable(metric):
        return None
    try:
        return int(metric())
    except (TypeError, ValueError, NotImplementedError):
        return None


@router.get("/candles")
def candle_completeness_health(refresh: bool = False):
    cached = get_cached_candle_completeness_report()
    if refresh or cached is None:
        return run_candle_completeness_job()
    return cached


@router.get("/database-storage")
def database_storage_health(table_limit: int = 25):
    return build_database_storage_report(
        engine,
        get_settings(),
        table_limit=table_limit,
    )


@router.get("/exit-protection", response_model=ExitProtectionHealth)
def exit_protection_health():
    """Return the worker heartbeat, shared through canonical storage in split deployments."""

    return exit_protection_snapshot()


@router.get("/pipeline", response_model=PipelineHealthResponse)
def pipeline_health():
    exit_protection = exit_protection_snapshot()
    if USING_SQLITE_FALLBACK:
        return {
            "source": "pipeline_run_ledger",
            "available": False,
            "ready": False,
            "paper_execution_allowed": False,
            "reason": "SQLITE_FALLBACK",
            "exit_protection": exit_protection,
        }

    db = SessionLocal()
    try:
        repo = PipelineRunRepository()
        pipeline = repo.latest_pipeline(db)
        if pipeline is None:
            return {
                "source": "pipeline_run_ledger",
                "available": True,
                "ready": False,
                "paper_execution_allowed": False,
                "reason": "NO_PIPELINE_RUN",
                "exit_protection": exit_protection,
            }

        readiness = repo.readiness(db, pipeline.id, PIPELINE_REQUIRED_STAGES)
        pipeline_completed = pipeline.status == "COMPLETED"
        # The lineage tables are actively written throughout a running cycle.
        # Counting every table here can wait behind those writes and make the
        # supervisor mistake database contention for an unresponsive API.
        lineage_counts = (
            repo.lineage_counts(db, pipeline.generation_id)
            if pipeline_completed
            else {}
        )
        pipeline_ready = bool(
            readiness["ready"] and pipeline_completed
        )
        exit_protection_ready = exit_protection.get("ready") is True
        unready_reason = _pipeline_unready_reason(
            pipeline,
            readiness,
            pipeline_ready=pipeline_ready,
            exit_protection_ready=exit_protection_ready,
        )
        return {
            "source": "pipeline_run_ledger",
            "available": True,
            "ready": pipeline_ready,
            "paper_execution_allowed": bool(
                pipeline_ready and exit_protection_ready
            ),
            "reason": unready_reason,
            "exit_protection": exit_protection,
            "pipeline": {
                "id": pipeline.id,
                "generation_id": pipeline.generation_id,
                "status": pipeline.status,
                "execution_scope": pipeline.execution_scope,
                "started_at": pipeline.started_at,
                "completed_at": pipeline.completed_at,
                "error_category": pipeline.error_category,
            },
            "readiness": {
                "required_stages": readiness["required_stages"],
                "missing_stages": readiness["missing_stages"],
                "failed_stages": readiness["failed_stages"],
                "running_stages": readiness.get("running_stages", []),
                "degraded_stages": readiness.get("degraded_stages", []),
                "blocked_stages": readiness.get("blocked_stages", []),
            },
            "lineage": {
                "generation_id": pipeline.generation_id,
                "derived_row_counts": lineage_counts,
                "verified": bool(
                    pipeline_completed
                    and readiness["ready"]
                    and any(lineage_counts.values())
                ),
            },
            "jobs": [
                {
                    "job_id": job.job_id,
                    "status": job.status,
                    "rows_read": job.rows_read,
                    "rows_written": job.rows_written,
                    "started_at": job.started_at,
                    "completed_at": job.completed_at,
                    "error_category": job.error_category,
                }
                for job in readiness["jobs"]
            ],
        }
    except Exception as exc:
        return {
            "source": "pipeline_run_ledger",
            "available": False,
            "ready": False,
            "paper_execution_allowed": False,
            "reason": str(exc),
            "exit_protection": exit_protection,
        }
    finally:
        db.close()


def _pipeline_unready_reason(
    pipeline,
    readiness,
    *,
    pipeline_ready,
    exit_protection_ready,
):
    if str(pipeline.status).upper() == "RUNNING":
        return "PIPELINE_RUNNING"
    if readiness.get("failed_stages"):
        return "REQUIRED_STAGE_FAILED"
    if readiness.get("blocked_stages"):
        return "REQUIRED_STAGE_BLOCKED"
    if readiness.get("degraded_stages"):
        return "REQUIRED_STAGE_DEGRADED"
    if readiness.get("missing_stages"):
        return "REQUIRED_STAGE_MISSING"
    if not pipeline_ready:
        return "PIPELINE_" + str(pipeline.status or "UNREADY").upper()
    if not exit_protection_ready:
        return "EXIT_PROTECTION_UNREADY"
    return None
