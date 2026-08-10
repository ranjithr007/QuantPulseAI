from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    system: str
    version: str
    environment: str
    status: str
    scheduler_enabled: bool
    process_role: Literal["all", "api", "worker"]
    admin_auth_required: bool


class DependencyHealthResponse(BaseModel):
    database_configured: bool
    database_url_scheme: str
    active_database_scheme: str
    using_sqlite_fallback: bool
    evidence_storage: str


class PipelineSummary(BaseModel):
    id: str
    generation_id: str
    status: str
    execution_scope: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_category: Optional[str] = None


class PipelineReadiness(BaseModel):
    required_stages: List[str]
    missing_stages: List[str]
    failed_stages: List[str]


class PipelineLineage(BaseModel):
    generation_id: str
    derived_row_counts: Dict[str, int]
    verified: bool


class PipelineJobHealth(BaseModel):
    job_id: str
    status: str
    rows_read: int = 0
    rows_written: int = 0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_category: Optional[str] = None


class PipelineHealthResponse(BaseModel):
    source: str
    available: bool
    ready: bool
    paper_execution_allowed: bool
    reason: Optional[str] = None
    pipeline: Optional[PipelineSummary] = None
    readiness: Optional[PipelineReadiness] = None
    lineage: Optional[PipelineLineage] = None
    jobs: List[PipelineJobHealth] = Field(default_factory=list)
