from types import SimpleNamespace

import pytest

from app.intelligence.fusion.fusion_engine import FusionEngine
from app.intelligence.fusion.decision_engine import DecisionEngine


def _decision(score):
    data = SimpleNamespace(
        symbol="BTCUSDT",
        ml_score=score,
        regime_score=score,
        orderflow_score=score,
        smc_score=score,
        liquidation_score=score,
        whale_score=score,
    )
    return FusionEngine().analyze(data)


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (39.99, "NEUTRAL"),
        (40.0, "LONG"),
        (59.99, "LONG"),
        (60.0, "STRONG_LONG"),
        (-39.99, "NEUTRAL"),
        (-40.0, "SHORT"),
        (-59.99, "SHORT"),
        (-60.0, "STRONG_SHORT"),
    ],
)
def test_fusion_score_boundaries(score, expected):
    result = _decision(score)

    assert result["decision"] == expected
    assert result["confidence"] == pytest.approx(abs(score))
    assert DecisionEngine().decide(score) == (
        "WAIT" if expected == "NEUTRAL" else expected
    )
