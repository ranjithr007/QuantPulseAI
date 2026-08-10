from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class SymbolContextResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    symbol: Optional[str] = None
    timeframe: Optional[str] = None
    source: Optional[str] = None
    status: Optional[str] = None
    error: Optional[str] = None


class MarketCandlesResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    symbol: Optional[str] = None
    timeframe: Optional[str] = None
    source: Optional[str] = None
    status: Optional[str] = None
    candles: List[Dict[str, Any]] = Field(default_factory=list)
    error: Optional[str] = None


class DerivativesResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    symbol: str
    source: str
    status: str
    data_scope: Optional[str] = None
    error: Optional[str] = None


class FrozenDecisionEvaluationRequest(BaseModel):
    symbol: str
    timeframe: str = "1h"
    intelligence: Dict[str, Any]
    derivatives: Dict[str, Any] = Field(default_factory=dict)
    capital: float = Field(default=10_000, gt=0)
    risk_percent: float = Field(default=1, gt=0, le=100)


class FrozenDecisionEvaluationResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    source: str
    symbol: str
    timeframe: str
    signal: Dict[str, Any]
    contradiction: Dict[str, Any]
    risk: Dict[str, Any]
    executor: Dict[str, Any]
    parity: Dict[str, Any]
    leakage_status: str
