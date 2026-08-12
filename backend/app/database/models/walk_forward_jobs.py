from datetime import datetime

from sqlalchemy import Column, DateTime, Index, String, Text

from app.database.sqlserver import Base


class WalkForwardJob(Base):
    __tablename__ = "walk_forward_jobs"

    job_id = Column(String(32), primary_key=True)
    source = Column(String(40), nullable=False)
    status = Column(String(20), nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    parameters_json = Column(Text, nullable=False)
    response_json = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)


Index(
    "ix_walk_forward_jobs_status_created",
    WalkForwardJob.status,
    WalkForwardJob.created_at,
)

