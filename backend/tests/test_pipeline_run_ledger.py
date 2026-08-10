from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.models.pipeline_runs import JobRun, PipelineRun
from app.database.models.market_features import MarketFeature
from app.database.models.point_in_time_snapshots import FeatureSnapshot
from app.database.sqlserver import Base
from app.repositories.pipeline_run_repository import PipelineRunRepository


def test_pipeline_and_job_lifecycle_is_idempotent():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[PipelineRun.__table__, JobRun.__table__])
    session = sessionmaker(bind=engine)()
    repo = PipelineRunRepository()

    pipeline, created = repo.start_pipeline(session, "gen-001", metadata={"scope": "paper"})
    duplicate, duplicate_created = repo.start_pipeline(session, "gen-001")

    assert created is True
    assert duplicate_created is False
    assert duplicate.id == pipeline.id

    job, job_created = repo.start_job(
        session,
        pipeline.id,
        "feature",
        idempotency_key="gen-001:feature",
        input_generation_id="gen-001",
    )
    duplicate_job, duplicate_job_created = repo.start_job(
        session,
        pipeline.id,
        "feature",
        idempotency_key="gen-001:feature",
    )
    repo.finish_job(session, job.id, status="COMPLETED", rows_read=200, rows_written=1)
    repo.finish_pipeline(session, pipeline.id, status="COMPLETED")

    assert job_created is True
    assert duplicate_job_created is False
    assert duplicate_job.id == job.id
    assert session.get(type(job), job.id).status == "COMPLETED"
    assert session.get(type(pipeline), pipeline.id).status == "COMPLETED"


def test_readiness_reports_missing_and_failed_required_stages():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[PipelineRun.__table__, JobRun.__table__])
    session = sessionmaker(bind=engine)()
    repo = PipelineRunRepository()

    pipeline, _ = repo.start_pipeline(session, "gen-readiness")
    market, _ = repo.start_job(
        session,
        pipeline.id,
        "market",
        idempotency_key="gen-readiness:market",
    )
    repo.finish_job(session, market.id, status="COMPLETED")
    feature, _ = repo.start_job(
        session,
        pipeline.id,
        "feature",
        idempotency_key="gen-readiness:feature",
    )
    repo.finish_job(session, feature.id, status="FAILED", error_category="UPSTREAM")

    readiness = repo.readiness(
        session,
        pipeline.id,
        ("market", "feature", "risk"),
    )

    assert readiness["ready"] is False
    assert readiness["missing_stages"] == ["risk"]
    assert readiness["failed_stages"] == ["feature"]


def test_lineage_counts_are_scoped_to_one_generation():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add_all(
        [
            MarketFeature(Symbol="BTCUSDT", Timeframe="1h", data_generation_id="gen-a"),
            MarketFeature(Symbol="ETHUSDT", Timeframe="1h", data_generation_id="gen-b"),
            FeatureSnapshot(
                symbol="BTCUSDT",
                timeframe="1h",
                source_timestamp=datetime.utcnow(),
                effective_timestamp=datetime.utcnow(),
                feature_version="v1",
                quality_state="OK",
                data_generation_id="gen-a",
            ),
        ]
    )
    session.commit()

    counts = PipelineRunRepository().lineage_counts(session, "gen-a")

    assert counts["MarketFeatures"] == 1
    assert counts["feature_snapshots"] == 1
    assert counts["MarketRegimes"] == 0
