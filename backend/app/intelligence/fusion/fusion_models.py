from pydantic import BaseModel


class FusionInput(BaseModel):

    symbol: str

    ml_score: float

    regime_score: float

    orderflow_score: float

    smc_score: float

    liquidation_score: float

    whale_score: float


class FusionResult(BaseModel):

    symbol: str

    decision: str

    confidence: float

    reasons: list[str]
