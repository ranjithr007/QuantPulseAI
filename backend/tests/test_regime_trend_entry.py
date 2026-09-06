import copy
from datetime import datetime, timezone, timedelta

import pytest

from app.strategies.candidate_builders import build_regime_trend_entry_payload, build_regime_trend_payload
from test_multi_strategy_execution import _core_payload, _market_move


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_entry_candidate_preserves_fixed_exits_and_baseline(side):
    now = datetime.now(timezone.utc)
    core, spot = _core_payload(now), _market_move(now)
    if side == "SHORT":
        for item in core["timeframes"]:
            item["component_scores"] = copy.deepcopy(item["component_scores"])
            for key in ("feature", "regime"):
                item["component_scores"][key]["score"] *= -1
            item["component_scores"]["regime"]["value"] = "TRENDING_BEAR"
        for item in spot["spot"]["timeframes"]:
            item.update(ema20=705, spot_cvd_percent=-2)
            item["resistance"]["latest_rejected"] = True
    original = copy.deepcopy(core)
    result = build_regime_trend_entry_payload(core, spot)
    assert result["trigger"]["status"] == "READY"
    assert result["trigger"]["side"] == side
    assert result["trade_plan"]["exit_policy"] == "PAPER_STAGED_EXIT_V2"
    assert result["trade_plan"]["stop_loss_percent"] == .75
    assert core == original


@pytest.mark.parametrize("failure", ["range", "stale", "rejection", "cvd", "extended", "missing_timeframe"])
def test_entry_candidate_blocks_bad_location_and_data(failure):
    now = datetime.now(timezone.utc)
    core, spot = _core_payload(now), _market_move(now)
    for item in core["timeframes"]:
        item["component_scores"] = copy.deepcopy(item["component_scores"])
        if failure == "range":
            item["component_scores"]["regime"]["value"] = "RANGE_ACCUMULATION"
    for item in spot["spot"]["timeframes"]:
        if failure == "rejection":
            item["support"]["latest_rejected"] = False
        if failure == "cvd":
            item["spot_cvd_percent"] = -1
        if failure == "extended":
            item["ema20"] = 650
    if failure == "stale":
        spot["effective_timestamp"] = now - timedelta(hours=2)
    if failure == "missing_timeframe":
        core["timeframes"].pop()
    result = build_regime_trend_entry_payload(core, spot)
    assert result["trigger"]["status"] == "WAIT"
    assert result["trade_plan_validation"]["is_valid"] is False
    if failure != "missing_timeframe":
        assert build_regime_trend_payload(core)["trigger"]["status"] == "READY"
