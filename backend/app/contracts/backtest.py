from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class BacktestResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    source: Optional[str] = None
    symbol: Optional[str] = None
    signal: Optional[str] = None
    timeframe: Optional[str] = None
    result: Any = None
    status: Optional[str] = None
    error: Optional[str] = None
