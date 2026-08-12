from copy import deepcopy

from app.backtesting.filtered_replay_engine import build_candle_decision
from app.backtesting.filtered_replay_engine import _new_directional_entry_funnel
from app.backtesting.filtered_replay_engine import _serialize_directional_entry_funnel
from app.backtesting.filtered_replay_engine import _update_directional_entry_funnel


def _features(side):
    if side == "LONG":
        values = {
            "trend_score": 70,
            "trend": "BULLISH",
            "momentum_score": 45,
            "final_score": 65,
        }
    else:
        values = {
            "trend_score": 35,
            "trend": "BEARISH",
            "momentum_score": 55,
            "final_score": 35,
        }
    return {
        "feature": {
            **values,
            "volatility_score": 50,
            "liquidity_score": 60,
            "atr": 1,
        }
    }


def _local_intelligence(side, *, confirmed):
    if side == "LONG":
        signal = "BUY" if confirmed else "SELL"
        delta = 10 if confirmed else -10
        bias = "LONG" if confirmed else "SHORT"
        direction = "BULLISH" if confirmed else "BEARISH"
    else:
        signal = "SELL" if confirmed else "BUY"
        delta = -10 if confirmed else 10
        bias = "SHORT" if confirmed else "LONG"
        direction = "BEARISH" if confirmed else "BULLISH"
    return {
        "orderflow": {
            "signal": signal,
            "delta": delta,
            "buyer_strength": 60 if side == "LONG" and confirmed else 40,
            "seller_strength": 60 if side == "SHORT" and confirmed else 40,
            "buy_volume": 60 if side == "LONG" and confirmed else 40,
            "sell_volume": 60 if side == "SHORT" and confirmed else 40,
        },
        "smc": {
            "bias": bias,
            "bos": {"detected": confirmed, "direction": direction},
        },
    }


def _stack(side, *, confirmed=True, regime=None):
    regime = regime or ("BULL_PULLBACK" if side == "LONG" else "BEAR_RALLY")
    opposite = "SHORT" if side == "LONG" else "LONG"
    return {
        "status": "READY",
        "decision_chain_timeframe": "4h",
        "timeframes": [
            {
                "timeframe": "1h",
                "bias": "NEUTRAL",
                "intelligence": _local_intelligence(opposite, confirmed=True),
            },
            {"timeframe": "2h", "bias": "NEUTRAL", "intelligence": {}},
            {
                "timeframe": "4h",
                "bias": "NEUTRAL",
                "intelligence": {
                    **_local_intelligence(side, confirmed=confirmed),
                    "regime": {"regime": regime, "confidence": 80},
                },
            },
            {"timeframe": "1d", "bias": "NEUTRAL", "intelligence": {}},
        ],
        "confirmation": {
            "trade_permission": f"{side}_ALLOWED",
            "stack_state": "MIXED_LIGHT",
            "confidence_penalty": 0,
        },
        "decision_chain": {
            "signal": {"signal": side},
            "contradiction": {"trade_allowed": True},
            "risk": {"decision": "APPROVE"},
            "executor": {"verdict": "WOULD_QUEUE"},
        },
    }


def _decision(side, profile, *, confirmed=True, min_confidence=70, regime=None):
    candle = type("Candle", (), {"candle_time": "2026-01-01T00:00:00"})()
    return build_candle_decision(
        [candle],
        side,
        min_confidence,
        feature_resolver=lambda _timestamp: _features(side),
        stack_context=_stack(side, confirmed=confirmed, regime=regime),
        gate_profile=profile,
    )


def test_regime_expansion_only_keeps_incompatible_feature_gates():
    decision = _decision("LONG", "DIRECTIONAL_REGIME_EXPANSION_RESEARCH")

    assert decision["eligible"] is False
    assert "REGIME_NOT_BULLISH" not in decision["blocked_reasons"]
    assert "MOMENTUM_NOT_BULLISH" in decision["blocked_reasons"]
    assert "FEATURE_SIGNAL_NOT_LONG" in decision["blocked_reasons"]


def test_confirmed_long_pullback_substitutes_only_feature_entry_gates():
    decision = _decision("LONG", "DIRECTIONAL_ENTRY_CONFIRMATION_RESEARCH")

    assert decision["eligible"] is True
    evidence = decision["research_gate_evidence"]["directional_entry_confirmation"]
    assert evidence["confirmed"] is True
    assert evidence["decision_timeframe"] == "4h"
    assert evidence["replaced_gate_rejections"] == [
        "FEATURE_SIGNAL_NOT_LONG",
        "MOMENTUM_NOT_BULLISH",
    ]


def test_confirmed_short_rally_substitutes_only_feature_entry_gates():
    decision = _decision("SHORT", "DIRECTIONAL_ENTRY_CONFIRMATION_RESEARCH")

    assert decision["eligible"] is True
    evidence = decision["research_gate_evidence"]["directional_entry_confirmation"]
    assert evidence["confirmed"] is True
    assert evidence["replaced_gate_rejections"] == ["MOMENTUM_NOT_BEARISH"]


def test_missing_local_confirmation_blocks_the_alternative_branch():
    decision = _decision(
        "LONG",
        "DIRECTIONAL_ENTRY_CONFIRMATION_RESEARCH",
        confirmed=False,
    )

    assert decision["eligible"] is False
    assert "DIRECTIONAL_ENTRY_CONFIRMATION_NOT_CONFIRMED" in decision["blocked_reasons"]
    assert "MOMENTUM_NOT_BULLISH" in decision["blocked_reasons"]


def test_confirmation_does_not_bypass_minimum_confidence():
    decision = _decision(
        "LONG",
        "DIRECTIONAL_ENTRY_CONFIRMATION_RESEARCH",
        min_confidence=90,
    )

    assert decision["eligible"] is False
    assert "CONFIDENCE_BELOW_THRESHOLD" in decision["blocked_reasons"]


def test_confirmation_is_not_applied_to_wrong_side_directional_regime():
    decision = _decision(
        "LONG",
        "DIRECTIONAL_ENTRY_CONFIRMATION_RESEARCH",
        regime="BEAR_RALLY",
    )

    assert decision["eligible"] is False
    assert "REGIME_NOT_BULLISH" in decision["blocked_reasons"]
    assert decision["research_gate_evidence"] == {}


def test_production_strict_profile_remains_unchanged():
    decision = _decision("LONG", "STRICT")

    assert decision["eligible"] is False
    assert "REGIME_NOT_BULLISH" in decision["blocked_reasons"]
    assert decision["research_gate_evidence"] == {}


def test_joint_funnel_is_read_only_and_reconciles_an_eligible_candidate():
    decision = _decision("LONG", "DIRECTIONAL_ENTRY_CONFIRMATION_RESEARCH")
    original = deepcopy(decision)
    diagnostics = _new_directional_entry_funnel()

    _update_directional_entry_funnel(diagnostics, decision, "LONG", 70)
    result = _serialize_directional_entry_funnel(diagnostics)

    assert decision == original
    assert result["candidate_regimes"] == {"BULL_PULLBACK": 1}
    assert all(value == 1 for value in result["cumulative_stage_counts"].values())
    assert result["first_failure_counts"] == {}
    distributions = result["confirmed_candidate_score_distributions"]
    assert distributions["composite_confidence"]["count"] == 1
    assert distributions["composite_confidence"]["average"] == 72.5
    assert distributions["directional_strength"]["average"] == 65.0
    assert distributions["regime_confidence"]["average"] == 80.0
    assert distributions["timeframe_penalty"]["average"] == 0.0
    audit = result["master_candidate_chain_audit"]
    assert audit["evaluated"] == 1
    assert audit["contradiction_statuses"] == {"UNKNOWN": 1}
    assert audit["current_price_availability"] == {"MISSING": 1}
    assert result["contract"]["first_failures_reconcile_to_candidates"] is True


def test_joint_funnel_reports_the_first_intersection_failure():
    decision = _decision(
        "LONG",
        "DIRECTIONAL_ENTRY_CONFIRMATION_RESEARCH",
        confirmed=False,
    )
    diagnostics = _new_directional_entry_funnel()

    _update_directional_entry_funnel(diagnostics, decision, "LONG", 70)
    result = _serialize_directional_entry_funnel(diagnostics)

    assert result["cumulative_stage_counts"]["SAME_SIDE_CANDIDATE_REGIME"] == 1
    assert result["cumulative_stage_counts"]["LOCAL_CONFIRMATION"] == 0
    assert result["independent_condition_pass_counts"][
        "CONFIDENCE_AT_OR_ABOVE_THRESHOLD"
    ] == 1
    assert result["first_failure_counts"] == {"LOCAL_CONFIRMATION": 1}
    assert result["contract"]["first_failures_reconcile_to_candidates"] is True


def test_joint_funnel_independent_counts_use_candidate_denominator_only():
    decision = _decision(
        "LONG",
        "DIRECTIONAL_ENTRY_CONFIRMATION_RESEARCH",
        regime="BEAR_RALLY",
    )
    diagnostics = _new_directional_entry_funnel()

    _update_directional_entry_funnel(diagnostics, decision, "LONG", 70)
    result = _serialize_directional_entry_funnel(diagnostics)

    assert result["contract"]["candidate_denominator"] == 0
    assert not any(result["independent_condition_pass_counts"].values())
    assert all(
        distribution["count"] == 0
        for distribution in result[
            "confirmed_candidate_score_distributions"
        ].values()
    )
    assert result["first_failure_counts"] == {}
