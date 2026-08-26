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
}

STRATEGY_REGISTRY = {
    CORE_SIGNAL_STRATEGY_ID: CORE_SIGNAL_STRATEGY,
    MARKET_MOVE_STRATEGY_ID: MARKET_MOVE_STRATEGY,
    CORE_FUSION_STRATEGY_ID: CORE_FUSION_STRATEGY,
}


def strategy_definition(strategy_id):
    return STRATEGY_REGISTRY.get(str(strategy_id or "").upper())
