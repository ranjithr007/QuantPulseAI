import json
from datetime import datetime
from uuid import uuid4

from app.database.models.pipeline_runs import JobRun, PipelineRun
from app.database.models.fusion_signal import FusionSignal
from app.database.models.market_features import MarketFeature
from app.database.models.market_order_flow import MarketOrderFlow
from app.database.models.market_regimes import MarketRegime
from app.database.models.market_smc import MarketSMCSignal
from app.database.models.point_in_time_snapshots import DecisionSnapshot, FeatureSnapshot
from app.database.models.risk_decision import RiskDecision
from app.database.models.trade_plan import TradePlan
from app.repositories._db_utils import commit_or_rollback


def _json(value):
    return json.dumps(value or {}, default=str, sort_keys=True)


class PipelineRunRepository:
    def latest_pipeline(self, db):
        return (
            db.query(PipelineRun)
            .order_by(PipelineRun.started_at.desc(), PipelineRun.id.desc())
            .first()
        )

    def jobs_for_pipeline(self, db, pipeline_run_id):
        return (
            db.query(JobRun)
            .filter(JobRun.pipeline_run_id == pipeline_run_id)
            .order_by(JobRun.started_at.asc(), JobRun.id.asc())
            .all()
        )

    def readiness(self, db, pipeline_run_id, required_stages):
        jobs = self.jobs_for_pipeline(db, pipeline_run_id)
        by_job = {job.job_id: job for job in jobs}
        missing = [stage for stage in required_stages if stage not in by_job]
        failed = [
            stage
            for stage in required_stages
            if stage in by_job and by_job[stage].status != "COMPLETED"
        ]
        return {
            "ready": not missing and not failed,
            "required_stages": list(required_stages),
            "missing_stages": missing,
            "failed_stages": failed,
            "jobs": jobs,
        }

    def lineage_counts(self, db, generation_id):
        models = (
            MarketFeature,
            MarketRegime,
            MarketOrderFlow,
            MarketSMCSignal,
            FusionSignal,
            RiskDecision,
            TradePlan,
            FeatureSnapshot,
            DecisionSnapshot,
        )
        return {
            model.__tablename__: db.query(model)
            .filter(model.data_generation_id == generation_id)
            .count()
            for model in models
        }

    def start_pipeline(
        self,
        db,
        generation_id,
        *,
        source_cutoff=None,
        execution_scope="PAPER_ONLY",
        metadata=None,
    ):
        existing = (
            db.query(PipelineRun)
            .filter(PipelineRun.generation_id == generation_id)
            .first()
        )
        if existing is not None:
            return existing, False

        record = PipelineRun(
            id=f"pipeline-{uuid4().hex}",
            generation_id=generation_id,
            status="RUNNING",
            execution_scope=execution_scope,
            source_cutoff=source_cutoff,
            metadata_json=_json(metadata),
        )
        db.add(record)
        commit_or_rollback(db)
        db.refresh(record)
        return record, True

    def finish_pipeline(
        self,
        db,
        pipeline_run_id,
        *,
        status,
        error_category=None,
        error_message=None,
    ):
        record = db.get(PipelineRun, pipeline_run_id)
        if record is None:
            raise LookupError(f"Unknown pipeline run: {pipeline_run_id}")
        record.status = status
        record.completed_at = datetime.utcnow()
        record.error_category = error_category
        record.error_message = error_message
        commit_or_rollback(db)
        db.refresh(record)
        return record

    def start_job(
        self,
        db,
        pipeline_run_id,
        job_id,
        *,
        idempotency_key,
        input_generation_id=None,
        metadata=None,
    ):
        existing = (
            db.query(JobRun)
            .filter(JobRun.idempotency_key == idempotency_key)
            .first()
        )
        if existing is not None:
            return existing, False

        record = JobRun(
            id=f"job-{uuid4().hex}",
            pipeline_run_id=pipeline_run_id,
            job_id=job_id,
            idempotency_key=idempotency_key,
            input_generation_id=input_generation_id,
            metadata_json=_json(metadata),
        )
        db.add(record)
        commit_or_rollback(db)
        db.refresh(record)
        return record, True

    def finish_job(
        self,
        db,
        job_run_id,
        *,
        status,
        rows_read=0,
        rows_written=0,
        output_generation_id=None,
        error_category=None,
        error_message=None,
    ):
        record = db.get(JobRun, job_run_id)
        if record is None:
            raise LookupError(f"Unknown job run: {job_run_id}")
        record.status = status
        record.rows_read = int(rows_read or 0)
        record.rows_written = int(rows_written or 0)
        record.output_generation_id = output_generation_id
        record.error_category = error_category
        record.error_message = error_message
        record.completed_at = datetime.utcnow()
        commit_or_rollback(db)
        db.refresh(record)
        return record
