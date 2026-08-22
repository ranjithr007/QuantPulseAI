from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class BundleFailure(BaseModel):
    section: Optional[str] = None
    error: Optional[str] = None


class IntelligenceBundleResponse(BaseModel):
    symbol: str
    timeframe: str
    mode: Optional[str] = None
    stale_after_seconds: int
    source: str
    signal: Any = None
    diagnostics: Any = None
    candles: Any = None
    orderflow: Any = None
    smc: Any = None
    risk: Any = None
    aiScores: Any = None
    derivatives: Any = None
    multiTimeframe: Any = None
    tradeSetup: Any = None
    entryTrigger: Any = None
    predictionContext: Any = None
    prediction: Any = None
    timing: Any = None
    bundleStatus: Optional[str] = None
    failures: List[BundleFailure] = Field(default_factory=list)


class PaperTradeBundleResponse(BaseModel):
    source: str
    symbol_filter: Optional[str] = None
    database_status: Optional[str] = None
    message: Optional[str] = None
    marketContext: Any = None
    accountRisk: Any = None
    paperWallet: Any = None
    ledgerScope: Any = None
    performance: Optional[Dict[str, Any]] = None
    summary: Optional[Dict[str, Any]] = None
    openTrades: Optional[Dict[str, Any]] = None
    closedTrades: Optional[Dict[str, Any]] = None


class RiskBundleResponse(BaseModel):
    symbol: str
    timeframe: str
    mode: Optional[str] = None
    stale_after_seconds: int
    source: str
    status: str
    data_scope: str
    error: Optional[str] = None
    risk: Any = None
    computedRisk: Any = None
    signal: Any = None
    multiTimeframe: Any = None
    predictionContext: Any = None
    derivatives: Any = None
    paperTrades: Any = None
    auto: Any = None
    autoDecision: Any = None
