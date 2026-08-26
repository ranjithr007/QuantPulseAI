"""Governed paper-strategy registry.

Strategy identifiers are durable database keys. Display names may change, but an
existing identifier/version pair must never be repurposed for different trading
rules. New behavior requires a new version.
"""

CORE_FUSION_STRATEGY_ID = "CORE_FUSION"
CORE_FUSION_STRATEGY_VERSION = "core_fusion_v1"
CORE_FUSION_DECISION_VERSION = "core_fusion_strategy_v1"
LEGACY_UNATTRIBUTED_STRATEGY_ID = "LEGACY_UNATTRIBUTED"
LEGACY_UNATTRIBUTED_STRATEGY_VERSION = "pre_strategy_lineage_v0"

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
    "status": "ACTIVE",
    "signal_threshold": 40.0,
    "full_size_threshold": 60.0,
    "official_timeframes": ["1h", "2h", "4h", "1d"],
    "requires_market_participation_confirmation": True,
    "one_active_trade_per_symbol": True,
}

STRATEGY_REGISTRY = {
    CORE_FUSION_STRATEGY_ID: CORE_FUSION_STRATEGY,
}


def strategy_definition(strategy_id):
    return STRATEGY_REGISTRY.get(str(strategy_id or "").upper())
