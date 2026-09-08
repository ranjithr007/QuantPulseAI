import copy
from datetime import datetime, timedelta, timezone

import pytest

from app.strategies.entry_quality import ENTRY_PROFILE
from app.strategies.entry_quality import build_market_move_experiment_payload
from app.strategies.entry_quality import revalidate_entry_candidate
from app.strategies.registry import MARKET_MOVE_STRATEGY, MARKET_MOVE_ENTRY_STRATEGY, MARKET_MOVE_EXIT_STRATEGY


def _evidence(side="LONG"):
    sign = 1 if side == "LONG" else -1
    now = datetime.now(timezone.utc)
    return {
        "profile": ENTRY_PROFILE, "side": side, "planned_entry": 100,
        "atr": 2, "ema20": 100 - sign, "structure_level": 100 - sign * 1.5,
        "spot_cvd_percent": sign * 10, "tested_rejection": True,
        "effective_timestamp": now.isoformat(),
    }


def _candidate(side="LONG"):
    return {"side": side, "trade_plan": {"strategy_id": "MARKET_MOVE_ENTRY", "strategy_version": "market_move_entry_v1", "side": side},
            "entry_quality": _evidence(side)}


def _mark(price=100):
    return {"mark_price": price, "observed_at": datetime.now(timezone.utc)}


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_directional_retest_gate_and_bounded_fresh_execution(side):
    evidence, reason = revalidate_entry_candidate(_candidate(side), _mark())
    assert reason is None
    assert evidence["entry_quality_passed"] is True
    assert evidence["entry_drift_atr"] == 0


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_chasing_retest_is_rejected_at_execution(side):
    price = 102 if side == "LONG" else 98
    _, reason = revalidate_entry_candidate(_candidate(side), _mark(price))
    assert "0.5 ATR" in reason


@pytest.mark.parametrize("field,value,reason_fragment", [
    ("tested_rejection", False, "tested"),
    ("spot_cvd_percent", -2, "CVD"),
    ("atr", float("nan"), "finite"),
    ("structure_level", 101, "boundary"),
    ("ema20", 101, "EMA"),
    ("side", "SHORT", "direction"),
    ("effective_timestamp", "invalid", "timestamp"),
])
def test_entry_gate_fails_closed(field, value, reason_fragment):
    candidate = _candidate()
    candidate["entry_quality"][field] = value
    _, reason = revalidate_entry_candidate(candidate, _mark())
    assert reason_fragment in reason


def test_fresh_price_does_not_rescue_stale_setup():
    candidate = _candidate()
    candidate["entry_quality"]["effective_timestamp"] = datetime.now(timezone.utc) - timedelta(minutes=16)
    _, reason = revalidate_entry_candidate(candidate, _mark())
    assert "stale" in reason


def test_missing_candidate_metadata_cannot_bypass_execution_gate():
    _, reason = revalidate_entry_candidate({"trade_plan": {"strategy_id": "MARKET_MOVE_ENTRY"}}, _mark())
    assert "missing" in reason
    assert revalidate_entry_candidate({"trade_plan": {"strategy_id": "MARKET_MOVE"}}, _mark()) == ({}, None)


def _payload(side="LONG"):
    quality = _evidence(side)
    zone_name = "support" if side == "LONG" else "resistance"
    edge = "lower" if side == "LONG" else "upper"
    return {
        "symbol": "BTCUSDT", "confirmation": {"confidence": 40},
        "trigger": {"status": "READY", "side": side, "entry_timeframe": "1h"},
        "trade_plan": {"entry": 100, "stop_loss": 97.5, "target1": 104, "target2": 106,
                       "exit_policy": "PAPER_ATR_STRUCTURE_V1"},
        "trade_plan_validation": {"is_valid": True, "errors": []},
        "timeframes": [{"timeframe": "1h", "atr": quality["atr"], "ema20": quality["ema20"],
                        "spot_cvd_percent": quality["spot_cvd_percent"],
                        zone_name: {edge: quality["structure_level"], "tests": 2, "latest_rejected": True}}],
    }, {"effective_timestamp": quality["effective_timestamp"]}


@pytest.mark.parametrize("entry_only", [True, False])
def test_experiments_do_not_mutate_incumbent_or_original_exits(entry_only):
    baseline, participation = _payload()
    original = copy.deepcopy(baseline)
    result = build_market_move_experiment_payload(baseline, participation, entry_only=entry_only)
    assert baseline == original
    assert result["trigger"] == original["trigger"]
    assert result["confirmation"] == {"confidence": 40}
    for field in ("entry", "stop_loss", "target1", "target2", "exit_policy"):
        assert result["trade_plan"][field] == baseline["trade_plan"][field]
    assert result["trailing_activation_r"] == (0.0 if entry_only else 1.0)


def test_entry_only_filters_bad_location_exit_only_preserves_same_entry():
    baseline, participation = _payload()
    baseline["timeframes"][0]["support"]["latest_rejected"] = False
    entry = build_market_move_experiment_payload(baseline, participation, entry_only=True)
    exit_only = build_market_move_experiment_payload(baseline, participation, entry_only=False)
    assert entry["trigger"]["status"] == "WAIT"
    assert exit_only["trigger"]["status"] == "READY"


def test_ineligible_base_cannot_be_rescued_and_experiments_are_isolated():
    baseline, participation = _payload()
    baseline["trigger"].update(status="WAIT", side=None)
    for entry_only in (True, False):
        candidate = build_market_move_experiment_payload(baseline, participation, entry_only=entry_only)
        assert candidate["trigger"]["status"] == "WAIT"
    assert MARKET_MOVE_STRATEGY["official_execution_enabled"] is True
    for definition in (MARKET_MOVE_ENTRY_STRATEGY, MARKET_MOVE_EXIT_STRATEGY):
        assert definition["official_execution_enabled"] is False
        assert definition["immutable_experiment"] is True
        assert definition["execution_scope"] == "PAPER_ONLY"
        assert definition["signal_threshold"] == 40
