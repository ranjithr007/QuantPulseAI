from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class SchedulerJobContract(BaseModel):
    id: str
    name: Optional[str] = None
    module: Optional[str] = None
    function: Optional[str] = None
    trigger: Optional[str] = None
    seconds: Optional[int] = None
    minutes: Optional[int] = None
    max_instances: Optional[int] = None
    coalesce: Optional[bool] = None
    next_run_time: Optional[datetime] = None


class SchedulerJobsResponse(BaseModel):
    available: bool = True
    scheduler_enabled: Optional[bool] = None
    configured_jobs: List[str] = Field(default_factory=list)
    jobs: List[SchedulerJobContract] = Field(default_factory=list)
    error: Optional[str] = None


class SchedulerStatusResponse(BaseModel):
    available: bool = True
    running: bool = False
    jobs: List[SchedulerJobContract] = Field(default_factory=list)
    error: Optional[str] = None
    missing_dependency: Optional[str] = None
