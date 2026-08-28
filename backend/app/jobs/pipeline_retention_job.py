from datetime import datetime, timedelta

from app.config import get_settings
from app.database.sqlserver import SessionLocal
from app.repositories.pipeline_run_repository import PipelineRunRepository
from app.utils.network_resilience import summarize_network_error


def run_pipeline_retention_job():
    """Bound operational-ledger growth without deleting trading evidence."""
    settings = get_settings()
    cutoff = datetime.utcnow() - timedelta(days=settings.pipeline_retention_days)
    db = SessionLocal()
    try:
        repository = PipelineRunRepository()
        preview = repository.retention_preview(
            db,
            completed_before=cutoff,
            batch_size=settings.pipeline_retention_batch_size,
        )
        if not settings.pipeline_retention_enabled:
            return {
                "source": "pipeline_retention",
                "status": "DISABLED",
                "retention_days": settings.pipeline_retention_days,
                "preview": preview,
                "deleted_pipelines": 0,
                "deleted_jobs": 0,
            }

        result = repository.purge_completed_before(
            db,
            completed_before=cutoff,
            batch_size=settings.pipeline_retention_batch_size,
        )
        return {
            "source": "pipeline_retention",
            "status": "COMPLETED",
            "retention_days": settings.pipeline_retention_days,
            **result,
        }
    except Exception as exc:
        db.rollback()
        return {
            "source": "pipeline_retention",
            "status": "FAILED",
            "error": summarize_network_error(exc),
        }
    finally:
        db.close()
