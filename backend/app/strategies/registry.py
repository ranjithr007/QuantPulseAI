"""Governed paper-strategy registry.

Strategy identifiers are durable database keys. Display names may change, but an
existing identifier/version pair must never be repurposed for different trading
rules. New behavior requires a new version.
"""

CORE_FUSION_STRATEGY_ID = "CORE_FUSION"
CORE_FUSION_STRATEGY_VERSION = "core_fusion_v1"
CORE_FUSION_DECISION_VERSION = "core_fusion_strategy_v1"
CORE_SIGNAL_STRATEGY_ID = "CORE_SIGNAL"
CORE_SIGNAL_STRATEGY_VERSION = "core_signal_v1"
CORE_SIGNAL_DECISION_VERSION = "core_signal_strategy_v1"
MARKET_MOVE_STRATEGY_ID = "MARKET_MOVE"
MARKET_MOVE_STRATEGY_VERSION = "market_move_v1"
MARKET_MOVE_DECISION_VERSION = "market_move_strategy_v1"
REGIME_TREND_STRATEGY_ID = "REGIME_TREND"
REGIME_TREND_STRATEGY_VERSION = "regime_trend_v1"
REGIME_TREND_DECISION_VERSION = "regime_trend_strategy_v1"
ORDERFLOW_SMC_STRATEGY_ID = "ORDERFLOW_SMC"
ORDERFLOW_SMC_STRATEGY_VERSION = "orderflow_smc_v1"
ORDERFLOW_SMC_DECISION_VERSION = "orderflow_smc_strategy_v1"
LIQUIDATION_CARRY_STRATEGY_ID = "LIQUIDATION_CARRY"
LIQUIDATION_CARRY_STRATEGY_VERSION = "liquidation_carry_v1"
LIQUIDATION_CARRY_DECISION_VERSION = "liquidation_carry_strategy_v1"
TREND_PULLBACK_STRATEGY_ID = "TREND_PULLBACK"
TREND_PULLBACK_STRATEGY_VERSION = "trend_pullback_v2"
TREND_PULLBACK_DECISION_VERSION = "trend_pullback_strategy_v2"
RANGE_REVERSION_STRATEGY_ID = "RANGE_REVERSION"
RANGE_REVERSION_STRATEGY_VERSION = "range_reversion_v2"
RANGE_REVERSION_DECISION_VERSION = "range_reversion_strategy_v2"
LEGACY_UNATTRIBUTED_STRATEGY_ID = "LEGACY_UNATTRIBUTED"
LEGACY_UNATTRIBUTED_STRATEGY_VERSION = "pre_strategy_lineage_v0"

CORE_SIGNAL_STRATEGY = {
    "id": CORE_SIGNAL_STRATEGY_ID,
    "version": CORE_SIGNAL_STRATEGY_VERSION,
    "decision_version": CORE_SIGNAL_DECISION_VERSION,
    "name": "Core Signal",
    "description": (
        "Independent multi-timeframe feature, regime, order-flow and SMC "
        "signal using the official 1h/2h/4h/1d stack."
    ),
    "strategy_type": "INDIVIDUAL",
    "execution_scope": "PAPER_ONLY",
    "status": "ACTIVE",
    "signal_threshold": 40.0,
    "full_size_threshold": 60.0,
    "official_timeframes": ["1h", "2h", "4h", "1d"],
    "requires_core_signal": True,
    "requires_market_participation_confirmation": False,
    "one_active_trade_per_symbol": True,
    "execution_priority": 20,
    "official_execution_enabled": False,
}

MARKET_MOVE_STRATEGY = {
    "id": MARKET_MOVE_STRATEGY_ID,
    "version": MARKET_MOVE_STRATEGY_VERSION,
    "decision_version": MARKET_MOVE_DECISION_VERSION,
    "name": "Market Move",
    "description": (
        "Independent spot-participation strategy using the official timeframe "
        "stack, derivatives, breadth, liquidation and verified macro context."
    ),
    "strategy_type": "INDIVIDUAL",
    "execution_scope": "PAPER_ONLY",
    "status": "ACTIVE",
    "signal_threshold": 40.0,
    "full_size_threshold": 60.0,
    "official_timeframes": ["1h", "2h", "4h", "1d"],
    "requires_core_signal": False,
    "requires_market_participation_confirmation": True,
    "one_active_trade_per_symbol": True,
    "execution_priority": 20,
    "official_execution_enabled": False,
}

REGIME_TREND_STRATEGY = {
    "id": REGIME_TREND_STRATEGY_ID,
    "version": REGIME_TREND_STRATEGY_VERSION,
    "decision_version": REGIME_TREND_DECISION_VERSION,
    "name": "Regime Trend",
    "description": (
        "Independent trend-following strategy requiring aligned, fresh Feature "
        "and Regime evidence on the selected governed timeframe."
    ),
    "strategy_type": "INDIVIDUAL",
    "execution_scope": "PAPER_ONLY",
    "status": "ACTIVE",
    "signal_threshold": 40.0,
    "full_size_threshold": 60.0,
    "official_timeframes": ["1h", "2h", "4h", "1d"],
    "required_components": ["feature", "regime"],
    "requires_core_signal": False,
    "requires_market_participation_confirmation": False,
    "one_active_trade_per_symbol": True,
    "execution_priority": 20,
    "official_execution_enabled": False,
}

ORDERFLOW_SMC_STRATEGY = {
    "id": ORDERFLOW_SMC_STRATEGY_ID,
    "version": ORDERFLOW_SMC_STRATEGY_VERSION,
    "decision_version": ORDERFLOW_SMC_DECISION_VERSION,
    "name": "Order Flow SMC",
    "description": (
        "Independent structure strategy requiring aligned, fresh Order Flow "
        "and Smart Money Concepts evidence."
    ),
    "strategy_type": "INDIVIDUAL",
    "execution_scope": "PAPER_ONLY",
    "status": "ACTIVE",
    "signal_threshold": 40.0,
    "full_size_threshold": 60.0,
    "official_timeframes": ["1h", "2h", "4h", "1d"],
    "required_components": ["orderflow", "smc"],
    "requires_core_signal": False,
    "requires_market_participation_confirmation": False,
    "one_active_trade_per_symbol": True,
    "execution_priority": 20,
    "official_execution_enabled": False,
}

LIQUIDATION_CARRY_STRATEGY = {
    "id": LIQUIDATION_CARRY_STRATEGY_ID,
    "version": LIQUIDATION_CARRY_STRATEGY_VERSION,
    "decision_version": LIQUIDATION_CARRY_DECISION_VERSION,
    "name": "Liquidation Carry",
    "description": (
        "Independent futures-positioning strategy requiring observed liquidation "
        "pressure plus fresh funding and open-interest evidence."
    ),
    "strategy_type": "INDIVIDUAL",
    "execution_scope": "PAPER_ONLY",
    "status": "ACTIVE",
    "signal_threshold": 40.0,
    "full_size_threshold": 60.0,
    "official_timeframes": ["1h", "2h", "4h", "1d"],
    "required_components": ["funding", "open_interest", "liquidation"],
    "requires_core_signal": False,
    "requires_market_participation_confirmation": False,
    "one_active_trade_per_symbol": True,
    "execution_priority": 20,
    "official_execution_enabled": False,
}

CORE_FUSION_STRATEGY = {
    "id": CORE_FUSION_STRATEGY_ID,
    "version": CORE_FUSION_STRATEGY_VERSION,
    "decision_version": CORE_FUSION_DECISION_VERSION,
    "name": "Core Fusion",
    "description": (
        "Governed feature, regime, order-flow and SMC signal with independent "
        "market-participation confirmation and shared paper-risk controls."
    ),
    "execution_scope": "PAPER_ONLY",
    "strategy_type": "COMBINED",
    "status": "ACTIVE",
    "signal_threshold": 40.0,
    "full_size_threshold": 60.0,
    "official_timeframes": ["1h", "2h", "4h", "1d"],
    "requires_market_participation_confirmation": True,
    "requires_core_signal": True,
    "one_active_trade_per_symbol": True,
    "execution_priority": 30,
    "official_execution_enabled": False,
}

TREND_PULLBACK_STRATEGY = {
    "id": TREND_PULLBACK_STRATEGY_ID,
    "version": TREND_PULLBACK_STRATEGY_VERSION,
    "decision_version": TREND_PULLBACK_DECISION_VERSION,
    "name": "Trend Pullback",
    "description": (
        "Governed intraday trend entry after a pullback/rally, tested boundary "
        "rejection, EMA confirmation, directional spot CVD and fresh ATR."
    ),
    "strategy_type": "REGIME_ROUTED",
    "execution_scope": "PAPER_ONLY",
    "status": "ACTIVE",
    "signal_threshold": 40.0,
    "full_size_threshold": 60.0,
    "official_timeframes": ["1h", "2h", "4h", "1d"],
    "requires_core_signal": False,
    "requires_market_participation_confirmation": False,
    "one_active_trade_per_symbol": True,
    "execution_priority": 100,
    "official_execution_enabled": True,
    "enabled_modes": ["intraday"],
}

RANGE_REVERSION_STRATEGY = {
    "id": RANGE_REVERSION_STRATEGY_ID,
    "version": RANGE_REVERSION_STRATEGY_VERSION,
    "decision_version": RANGE_REVERSION_DECISION_VERSION,
    "name": "Range Reversion",
    "description": (
        "Governed intraday range-boundary entry after tested support/resistance "
        "rejection with directional spot CVD and fresh ATR."
    ),
    "strategy_type": "REGIME_ROUTED",
    "execution_scope": "PAPER_ONLY",
    "status": "ACTIVE",
    "signal_threshold": 40.0,
    "full_size_threshold": 60.0,
    "official_timeframes": ["1h", "2h", "4h", "1d"],
    "requires_core_signal": False,
    "requires_market_participation_confirmation": False,
    "one_active_trade_per_symbol": True,
    "execution_priority": 100,
    "official_execution_enabled": True,
    "enabled_modes": ["intraday"],
}

STRATEGY_REGISTRY = {
    CORE_SIGNAL_STRATEGY_ID: CORE_SIGNAL_STRATEGY,
    MARKET_MOVE_STRATEGY_ID: MARKET_MOVE_STRATEGY,
    REGIME_TREND_STRATEGY_ID: REGIME_TREND_STRATEGY,
    ORDERFLOW_SMC_STRATEGY_ID: ORDERFLOW_SMC_STRATEGY,
    LIQUIDATION_CARRY_STRATEGY_ID: LIQUIDATION_CARRY_STRATEGY,
    CORE_FUSION_STRATEGY_ID: CORE_FUSION_STRATEGY,
    TREND_PULLBACK_STRATEGY_ID: TREND_PULLBACK_STRATEGY,
    RANGE_REVERSION_STRATEGY_ID: RANGE_REVERSION_STRATEGY,
}


def strategy_definition(strategy_id):
    return STRATEGY_REGISTRY.get(str(strategy_id or "").upper())
