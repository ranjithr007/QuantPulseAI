import pytest

from app.api.v1.risk_api import _build_auto_decision


def _decision(confidence):
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
                "stack_state": "ALIGNED",
                "trade_permission": "LONG_ALLOWED",
                "confidence_penalty": 0,
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
def test_adjusted_confidence_entry_boundary(confidence, allowed):
    decision = _decision(confidence)

    assert decision["confidence"] == confidence
    assert decision["allowed"] is allowed
    assert ("Confidence below minimum" in decision["reasons"]) is (not allowed)
