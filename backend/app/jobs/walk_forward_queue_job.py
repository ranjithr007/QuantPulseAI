"""Worker-side processor for durable walk-forward validation requests."""

from app.backtesting.walk_forward_jobs import claim_next_walk_forward_job
from app.backtesting.walk_forward_jobs import load_walk_forward_job


def run_walk_forward_queue_job():
    record = claim_next_walk_forward_job()
    if record is None:
        return {
            "source": "walk_forward_worker_queue_v1",
            "status": "IDLE",
            "job_id": None,
        }

    # Imported lazily to keep scheduler discovery independent from API startup
    # and to reuse the same governed replay/report implementation.
    from app.api.v1.backtest_api import _run_walk_forward_validation_job

    _run_walk_forward_validation_job(record["job_id"], record["parameters"])
    completed = load_walk_forward_job(record["job_id"])
    return {
        "source": "walk_forward_worker_queue_v1",
        "status": (completed or {}).get("status") or "UNKNOWN",
        "job_id": record["job_id"],
        "error": (completed or {}).get("error"),
    }
