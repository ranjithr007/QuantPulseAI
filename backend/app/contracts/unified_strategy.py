"""Validated configuration contract for the Unified Composite strategy."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


EngineMode = Literal["OFF", "CONFIRM", "REQUIRED"]
Bias = Literal["LONG", "SHORT", "WAIT", "ALIGN"]
ExecutionMode = Literal["MANUAL_REVIEW", "PAPER_AUTO", "LIVE_AUTO"]


class SpotBiasPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    one_hour: EngineMode = Field(alias="1h")
    two_hour: EngineMode = Field(alias="2h")
    four_hour: EngineMode = Field(alias="4h")
    one_day: EngineMode = Field(alias="1d")


class UnifiedEnginePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    technical: EngineMode
    ai: EngineMode
    orderflow: EngineMode
    smc: EngineMode
    whale: EngineMode
    funding_oi: EngineMode
    liquidation: EngineMode
    volume: EngineMode
    macro: EngineMode
    regime: EngineMode
    spot_bias: SpotBiasPolicy


class UnifiedBiasPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required_direction: Literal["ALIGN"] = "ALIGN"
    minimum_confirmations: int = Field(default=3, ge=1, le=10)
    daily_opposite_blocks: bool = True
    macro_opposite_blocks: bool = False
    stale_input_action: Literal["WAIT"] = "WAIT"
    contradiction_action: Literal["WAIT"] = "WAIT"


class UnifiedEntryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["MARKET", "PULLBACK", "BREAKOUT_RETEST"]
    minimum_confidence: float = Field(ge=0, le=100)
    maximum_entry_slippage_percent: float = Field(gt=0, le=1)


class UnifiedExitPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target1_reward_to_risk: float = Field(gt=0)
    target1_close_fraction: float = Field(gt=0, lt=1)
    target2_reward_to_risk: float = Field(gt=0)
    trailing_activation_r: float = Field(gt=0)
    protection_mode: Literal["BREAKEVEN_AFTER_T1", "STRUCTURE_TRAIL", "NONE"]
    maximum_hold_hours: int = Field(gt=0, le=720)

    @model_validator(mode="after")
    def targets_are_ordered(self):
        if self.target2_reward_to_risk <= self.target1_reward_to_risk:
            raise ValueError("target2_reward_to_risk must exceed target1_reward_to_risk")
        return self


class UnifiedRiskPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stop_mode: Literal["ATR", "STRUCTURE_ATR", "FIXED_PERCENT"]
    atr_multiplier: float = Field(gt=0, le=5)
    risk_per_trade_percent: float = Field(gt=0, le=1)
    maximum_leverage: float = Field(gt=0, le=1)
    maximum_open_positions: int = Field(ge=1, le=10)
    daily_loss_limit_percent: float = Field(gt=0, le=5)
    weekly_loss_limit_percent: float = Field(gt=0, le=15)
    one_position_per_symbol: bool = True


class UnifiedExecutionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_only: Literal[True] = True
    live_enabled: Literal[False] = False
    allowed_symbols: list[str] = Field(min_length=1)


class UnifiedCompositeProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy_id: Literal["UNIFIED_COMPOSITE"] = "UNIFIED_COMPOSITE"
    mode: ExecutionMode = "MANUAL_REVIEW"
    execution: UnifiedExecutionPolicy
    engines: UnifiedEnginePolicy
    bias_policy: UnifiedBiasPolicy
    entry: UnifiedEntryPolicy
    exit: UnifiedExitPolicy
    risk: UnifiedRiskPolicy

    @model_validator(mode="after")
    def enforce_safe_mode(self):
        if self.mode == "LIVE_AUTO":
            raise ValueError("LIVE_AUTO is disabled; use MANUAL_REVIEW or PAPER_AUTO")
        if self.risk.weekly_loss_limit_percent < self.risk.daily_loss_limit_percent:
            raise ValueError("weekly loss limit must not be below daily loss limit")
        return self
