"""Preview completed-pipeline retention; execute only with --execute."""

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings  # noqa: E402
from app.database.sqlserver import SessionLocal  # noqa: E402
from app.jobs.pipeline_retention_job import run_pipeline_retention_job  # noqa: E402
from app.repositories.pipeline_run_repository import PipelineRunRepository  # noqa: E402


def build_preview():
    settings = get_settings()
    cutoff = datetime.utcnow() - timedelta(days=settings.pipeline_retention_days)
    db = SessionLocal()
    try:
        preview = PipelineRunRepository().retention_preview(
            db,
            completed_before=cutoff,
            batch_size=settings.pipeline_retention_batch_size,
        )
        return {
            "source": "pipeline_retention",
            "status": "PREVIEW_ONLY",
            "retention_enabled": settings.pipeline_retention_enabled,
            "retention_days": settings.pipeline_retention_days,
            "preview": preview,
            "deleted_pipelines": 0,
            "deleted_jobs": 0,
        }
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Run the configured deletion instead of a read-only preview.",
    )
    args = parser.parse_args()
    result = run_pipeline_retention_job() if args.execute else build_preview()
    print(json.dumps(result, default=str, indent=2))
