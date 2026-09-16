from app.database.sqlserver import SessionLocal
from app.repositories.pipeline_run_repository import PipelineRunRepository
from app.utils.network_resilience import summarize_network_error


def recover_abandoned_pipeline_runs(*, stale_after_seconds=1800):
    """Repair ledger rows left RUNNING when the previous process terminated."""
    db = SessionLocal()
    try:
        result = PipelineRunRepository().recover_stale_running(
            db,
            stale_after_seconds=stale_after_seconds,
        )
        if result["recovered_pipelines"]:
            print(
                "Recovered abandoned pipeline ledger rows at startup:",
                result,
            )
        return result
    except Exception as exc:
        db.rollback()
        print(
            "Pipeline startup ledger recovery failed:",
            summarize_network_error(exc),
        )
        return {
            "recovered_pipelines": 0,
            "recovered_jobs": 0,
            "pipeline_ids": [],
            "error": summarize_network_error(exc),
        }
    finally:
        db.close()
