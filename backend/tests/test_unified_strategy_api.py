import json
from pathlib import Path

from app.api.v1.unified_strategy_api import validate_profile
from app.api.v1 import unified_strategy_api
from app.contracts.unified_strategy import UnifiedCompositeProfile


def test_validate_profile_is_paper_only_and_creates_no_orders():
    path = Path(__file__).parents[1] / "docs" / "unified-composite-profile.example.json"
    profile = UnifiedCompositeProfile.model_validate(json.loads(path.read_text()))

    result = validate_profile(profile)

    assert result["status"] == "VALID"
    assert result["execution"] == "PAPER_ONLY"
    assert result["orders_created"] == 0
    assert result["profile"]["engines"]["spot_bias"]["1d"] == "CONFIRM"


def test_evaluate_profile_returns_wait_when_confidence_is_below_minimum(monkeypatch):
    path = Path(__file__).parents[1] / "docs" / "unified-composite-profile.example.json"
    profile = UnifiedCompositeProfile.model_validate(json.loads(path.read_text()))

    class Db:
        def close(self):
            pass

    monkeypatch.setattr(unified_strategy_api, "SessionLocal", lambda: Db())
    monkeypatch.setattr(
        unified_strategy_api,
        "build_contradiction_report",
        lambda db, symbol, timeframe: {
            "bias": "LONG", "trade_allowed": True, "confidence": 50,
            "reasons": ["test evidence"],
        },
    )

    result = unified_strategy_api.evaluate_profile("BTCUSDT", profile)

    assert result["status"] == "WAIT"
    assert result["orders_created"] == 0
    assert "below the profile minimum" in result["reasons"][-1]
