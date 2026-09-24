import json
from pathlib import Path

from app.api.v1.unified_strategy_api import validate_profile
from app.contracts.unified_strategy import UnifiedCompositeProfile


def test_validate_profile_is_paper_only_and_creates_no_orders():
    path = Path(__file__).parents[1] / "docs" / "unified-composite-profile.example.json"
    profile = UnifiedCompositeProfile.model_validate(json.loads(path.read_text()))

    result = validate_profile(profile)

    assert result["status"] == "VALID"
    assert result["execution"] == "PAPER_ONLY"
    assert result["orders_created"] == 0
    assert result["profile"]["engines"]["spot_bias"]["1d"] == "CONFIRM"
