from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class AutomationEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    source: str
    operation: Optional[str] = None
    status: Optional[str] = None
    changed: Optional[bool] = None
    settings: Any = None
    count: Optional[int] = None
    records: List[Dict[str, Any]] = Field(default_factory=list)
    error: Optional[str] = None


class LiveMarketResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    source: str
    status: Optional[str] = None
    available: Optional[bool] = None
    started: Optional[bool] = None
    count: Optional[int] = None
    records: List[Dict[str, Any]] = Field(default_factory=list)
    error: Optional[str] = None


class PaperTradeExecutionResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    source: str
    symbol_filter: Optional[str] = None
    candidate_count: int = 0
    executed_count: int = 0
    skipped_count: int = 0
    executed: List[Dict[str, Any]] = Field(default_factory=list)
    skipped: List[Dict[str, Any]] = Field(default_factory=list)
    database_status: Optional[str] = None
    message: Optional[str] = None


class MarketRefreshResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    source: str
    symbol: Optional[str] = None
    timeframe: Optional[str] = None
    status: Optional[str] = None
    saved_count: Optional[int] = None
    skipped_count: Optional[int] = None
    fetched_count: Optional[int] = None
    error: Optional[str] = None
