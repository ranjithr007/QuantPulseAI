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


class DatabasePoolHealth(BaseModel):
    implementation: str
    configured_size: int
    configured_max_overflow: int
    capacity: int
    checked_in: Optional[int] = None
    checked_out: Optional[int] = None
    overflow_in_use: Optional[int] = None
    utilization_percent: Optional[float] = None
    status: str


class DependencyHealthResponse(BaseModel):
    database_configured: bool
    database_url_scheme: str
    active_database_scheme: str
    using_sqlite_fallback: bool
    evidence_storage: str
    database_pool: Optional[DatabasePoolHealth] = None


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
    running_stages: List[str] = Field(default_factory=list)
    degraded_stages: List[str] = Field(default_factory=list)
    blocked_stages: List[str] = Field(default_factory=list)


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


class PriceStreamHealth(BaseModel):
    policy: str
    ready: bool
    connected: bool
    reason: Optional[str] = None
    max_age_seconds: float
    message_age_seconds: Optional[float] = None
    last_message_at: Optional[datetime] = None
    last_error: Optional[str] = None
    thread_alive: bool


class ExitProtectionHealth(BaseModel):
    policy: str
    ready: bool
    status: str
    reason: Optional[str] = None
    max_age_seconds: float
    age_seconds: Optional[float] = None
    last_attempt_at: Optional[datetime] = None
    last_success_at: Optional[datetime] = None
    last_worker_status: str
    last_duration_seconds: Optional[float] = None
    last_error: Optional[str] = None
    consecutive_failures: int = 0
    price_stream: Optional[PriceStreamHealth] = None


class PipelineHealthResponse(BaseModel):
    source: str
    available: bool
    ready: bool
    paper_execution_allowed: bool
    reason: Optional[str] = None
    pipeline: Optional[PipelineSummary] = None
    readiness: Optional[PipelineReadiness] = None
    lineage: Optional[PipelineLineage] = None
    exit_protection: Optional[ExitProtectionHealth] = None
    jobs: List[PipelineJobHealth] = Field(default_factory=list)
