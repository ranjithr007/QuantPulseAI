import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.contracts.unified_strategy import UnifiedCompositeProfile


PROFILE = Path(__file__).parents[1] / "docs" / "unified-composite-profile.example.json"


def test_example_profile_is_valid_and_paper_only():
    profile = UnifiedCompositeProfile.model_validate(json.loads(PROFILE.read_text()))

    assert profile.mode == "MANUAL_REVIEW"
    assert profile.execution.paper_only is True
    assert profile.execution.live_enabled is False
    assert profile.engines.spot_bias.one_day == "CONFIRM"
    assert profile.risk.maximum_leverage == 1


def test_live_mode_is_rejected():
    payload = json.loads(PROFILE.read_text())
    payload["mode"] = "LIVE_AUTO"

    with pytest.raises(ValidationError, match="LIVE_AUTO"):
        UnifiedCompositeProfile.model_validate(payload)


def test_invalid_target_order_and_loss_limits_are_rejected():
    payload = json.loads(PROFILE.read_text())
    payload["exit"]["target2_reward_to_risk"] = 0.5
    payload["risk"]["weekly_loss_limit_percent"] = 0.5

    with pytest.raises(ValidationError):
        UnifiedCompositeProfile.model_validate(payload)
