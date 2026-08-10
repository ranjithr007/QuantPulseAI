from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class SignalResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    symbol: str
    timeframe: str
    source: Optional[str] = None
    status: Optional[str] = None
    data_scope: Optional[str] = None

class SignalBatchResponse(BaseModel):
    source: str
    status: str
    data_scope: str
    timeframe: str
    count: int
    records: List[Dict[str, Any]] = Field(default_factory=list)
    records_by_symbol: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
