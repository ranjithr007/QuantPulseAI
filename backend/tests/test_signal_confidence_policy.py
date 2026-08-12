import pytest

from app.api.v1.risk_api import _build_auto_decision


def _decision(
    confidence,
    *,
    stack_state="ALIGNED",
    trade_permission="LONG_ALLOWED",
    legacy_penalty=0,
):
    return _build_auto_decision(
        auto={
            "enabled": True,
            "locked": False,
            "emergencyStop": False,
            "allowedSymbols": ["BTCUSDT"],
            "direction": "BOTH",
            "minConfidence": 60.0,
            "maxOpenTrades": 4,
            "dailyLossLimit": 4.0,
        },
        selected_symbol="BTCUSDT",
        signal={
            "signal": "LONG",
            "confidence": confidence,
            "current_price": 100.0,
            "trade_plan": {"risk_reward": 2.0},
        },
        risk={"is_usable": True},
        computed_risk=None,
        paper_bundle={
            "openTrades": {"records": []},
            "closedTrades": {"records": []},
        },
        multi_timeframe={
            "confirmation": {
                "stack_state": stack_state,
                "trade_permission": trade_permission,
                "confidence_penalty": legacy_penalty,
            }
        },
        derivatives={
            "availability": {"funding": True, "open_interest": True}
        },
    )


@pytest.mark.parametrize(
    ("confidence", "allowed"),
    [(59.99, False), (60.0, True), (60.01, True)],
)
def test_signal_confidence_entry_boundary(confidence, allowed):
    decision = _decision(confidence)

    assert decision["confidence"] == confidence
    assert decision["allowed"] is allowed
    assert ("Confidence below minimum" in decision["reasons"]) is (not allowed)


def test_legacy_timeframe_penalty_does_not_reduce_signal_confidence():
    decision = _decision(
        62.0,
        stack_state="MIXED_LIGHT",
        trade_permission="WAIT",
        legacy_penalty=15,
    )

    assert decision["confidence"] == 62.0
    assert decision["rawConfidence"] == 62.0
    assert "confidencePenalty" not in decision
    assert decision["allowed"] is True


def test_strong_timeframe_conflict_remains_a_separate_hard_block():
    decision = _decision(
        90.0,
        stack_state="MIXED_STRONG",
        trade_permission="WAIT",
        legacy_penalty=15,
    )

    assert decision["confidence"] == 90.0
    assert "confidencePenalty" not in decision
    assert decision["allowed"] is False
    assert "Higher timeframe conflict is too strong" in decision["reasons"]
