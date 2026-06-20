from datetime import datetime
from datetime import timezone
from traceback import format_exc

from fastapi import APIRouter, HTTPException, Query

from app.config import get_settings
from app.scheduler.registry import all_job_definitions
from app.scheduler.registry import get_job_definition


router = APIRouter(prefix="/scheduler", tags=["Scheduler"])


@router.get("/jobs")
def list_jobs():
    return {
        "scheduler_enabled": get_settings().start_scheduler,
        "configured_jobs": get_settings().scheduler_job_ids,
        "jobs": [definition.as_dict() for definition in all_job_definitions()],
    }


@router.get("/status")
def scheduler_status():
    try:
        from app.scheduler.scheduler import get_scheduler
    except ModuleNotFoundError as exc:
        return {
            "available": False,
            "running": False,
            "missing_dependency": exc.name,
            "jobs": [],
        }

    scheduler = get_scheduler()

    if scheduler is None:
        return {
            "available": True,
            "running": False,
            "jobs": [],
        }

    return {
        "available": True,
        "running": scheduler.running,
        "jobs": [
            {
                "id": job.id,
                "name": job.name,
                "next_run_time": job.next_run_time,
            }
            for job in scheduler.get_jobs()
        ],
    }


@router.post("/start")
def start_scheduler_endpoint(
    jobs: str | None = Query(
        default=None,
        description="Optional comma-separated scheduler job ids. Defaults to configured jobs.",
    ),
):
    job_ids = _parse_job_ids(jobs)

    try:
        from app.scheduler.scheduler import get_scheduler
        from app.scheduler.scheduler import start_scheduler
    except ModuleNotFoundError as exc:
        return {
            "available": False,
            "started": False,
            "running": False,
            "missing_dependency": exc.name,
            "jobs": [],
        }

    started = start_scheduler(job_ids)
    scheduler = get_scheduler()

    return {
        "available": True,
        "started": started,
        "running": bool(scheduler and scheduler.running),
        "jobs": _scheduler_jobs(scheduler),
    }


@router.post("/jobs/{job_id}/dry-run")
def dry_run_job(
    job_id: str,
    execute: bool = Query(
        default=False,
        description="When false, only validates that the job can be imported.",
    ),
):
    definition = get_job_definition(job_id)

    if definition is None:
        raise HTTPException(status_code=404, detail=f"Unknown scheduler job: {job_id}")

    started_at = datetime.now(timezone.utc)

    try:
        job_function = definition.load()
    except Exception as exc:
        return {
            "job": definition.as_dict(),
            "execute": execute,
            "status": "IMPORT_FAILED",
            "error": str(exc),
            "traceback": format_exc(),
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc),
        }

    if not execute:
        return {
            "job": definition.as_dict(),
            "execute": False,
            "status": "IMPORT_OK",
            "message": "Job import succeeded. Pass execute=true to run it once.",
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc),
        }

    try:
        result = job_function()
    except Exception as exc:
        return {
            "job": definition.as_dict(),
            "execute": True,
            "status": "EXECUTION_FAILED",
            "error": str(exc),
            "traceback": format_exc(),
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc),
        }

    return {
        "job": definition.as_dict(),
        "execute": True,
        "status": "EXECUTION_OK",
        "result": result,
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc),
    }


def _parse_job_ids(jobs):
    if not jobs:
        return None

    return [item.strip() for item in jobs.split(",") if item.strip()]


def _scheduler_jobs(scheduler):
    if scheduler is None:
        return []

    return [
        {
            "id": job.id,
            "name": job.name,
            "next_run_time": job.next_run_time,
        }
        for job in scheduler.get_jobs()
    ]
