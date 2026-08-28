from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.models.pipeline_runs import JobRun, PipelineRun
from app.repositories.pipeline_run_repository import PipelineRunRepository


NOW = datetime(2026, 8, 28, 12, 0)


def _pipeline(pipeline_id, *, completed_at, status="COMPLETED"):
    return PipelineRun(
        id=pipeline_id,
        generation_id=f"generation-{pipeline_id}",
        status=status,
        started_at=completed_at - timedelta(minutes=2),
        completed_at=completed_at,
    )


def _job(job_id, pipeline_id):
    return JobRun(
        id=job_id,
        pipeline_run_id=pipeline_id,
        job_id="feature",
        idempotency_key=f"key-{job_id}",
        status="COMPLETED",
        started_at=NOW - timedelta(days=40),
        completed_at=NOW - timedelta(days=40),
    )


def test_pipeline_retention_only_deletes_completed_rows_before_cutoff():
    engine = create_engine("sqlite:///:memory:")
    PipelineRun.__table__.create(bind=engine)
    JobRun.__table__.create(bind=engine)
    db = sessionmaker(bind=engine)()
    try:
        old = _pipeline("old", completed_at=NOW - timedelta(days=40))
        recent = _pipeline("recent", completed_at=NOW - timedelta(days=2))
        running = _pipeline(
            "running",
            completed_at=NOW - timedelta(days=40),
            status="RUNNING",
        )
        db.add_all([old, recent, running, _job("old-job", "old"), _job("recent-job", "recent")])
        db.commit()

        repository = PipelineRunRepository()
        preview = repository.retention_preview(
            db,
            completed_before=NOW - timedelta(days=30),
        )
        assert preview["pipeline_count"] == 1
        assert preview["job_count"] == 1
        assert db.query(PipelineRun).count() == 3

        result = repository.purge_completed_before(
            db,
            completed_before=NOW - timedelta(days=30),
        )
        assert result["deleted_pipelines"] == 1
        assert result["deleted_jobs"] == 1
        assert {item.id for item in db.query(PipelineRun).all()} == {"recent", "running"}
        assert {item.id for item in db.query(JobRun).all()} == {"recent-job"}
    finally:
        db.close()
