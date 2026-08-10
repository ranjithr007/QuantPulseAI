from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text

from app.database.sqlserver import Base


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id = Column(String(80), primary_key=True)
    generation_id = Column(String(100), nullable=False, unique=True, index=True)
    status = Column(String(20), nullable=False, default="RUNNING")
    execution_scope = Column(String(30), nullable=False, default="PAPER_ONLY")
    source_cutoff = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    error_category = Column(String(60), nullable=True)
    error_message = Column(Text, nullable=True)
    metadata_json = Column(Text, nullable=False, default="{}")


class JobRun(Base):
    __tablename__ = "pipeline_job_runs"

    id = Column(String(80), primary_key=True)
    pipeline_run_id = Column(String(80), ForeignKey("pipeline_runs.id"), nullable=False, index=True)
    job_id = Column(String(80), nullable=False)
    idempotency_key = Column(String(180), nullable=False, unique=True)
    status = Column(String(20), nullable=False, default="RUNNING")
    input_generation_id = Column(String(100), nullable=True)
    output_generation_id = Column(String(100), nullable=True)
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    rows_read = Column(Integer, nullable=False, default=0)
    rows_written = Column(Integer, nullable=False, default=0)
    error_category = Column(String(60), nullable=True)
    error_message = Column(Text, nullable=True)
    metadata_json = Column(Text, nullable=False, default="{}")


Index(
    "ix_pipeline_job_runs_pipeline_job",
    JobRun.pipeline_run_id,
    JobRun.job_id,
)
