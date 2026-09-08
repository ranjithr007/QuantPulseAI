import copy
import math
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.paper_trading.exit_evidence import read_evidence
from app.paper_trading.paper_trade_monitor import evaluate_paper_trade_exit
from app.repositories.paper_trade_repository import PaperTradeRepository
from app.repositories.strategy_shadow_trade_repository import StrategyShadowTradeRepository
from app.strategies.exit_experiments import build_exit_experiment_payload
from app.strategies.registry import (
    CORE_SIGNAL_ENTRY_STRATEGY,
    CORE_SIGNAL_EXIT_STRATEGY,
    CORE_SIGNAL_STRATEGY,
    MARKET_MOVE_ENTRY_STRATEGY,
    MARKET_MOVE_EXIT_STRATEGY,
    MARKET_MOVE_STRATEGY,
    REGIME_TREND_ENTRY_STRATEGY,
    REGIME_TREND_EXIT_STRATEGY,
    REGIME_TREND_STRATEGY,
    strategy_definition,
)
from test_strategy_shadow_trading import _candidate, _session


EXIT_DEFINITIONS = [
    CORE_SIGNAL_EXIT_STRATEGY,
    MARKET_MOVE_EXIT_STRATEGY,
    REGIME_TREND_EXIT_STRATEGY,
]
ENTRY_DEFINITIONS = [
    CORE_SIGNAL_ENTRY_STRATEGY,
    MARKET_MOVE_ENTRY_STRATEGY,
    REGIME_TREND_ENTRY_STRATEGY,
]
OPENED_AT = datetime(2026, 9, 1, 10)


def _payload(side):
    sign = 1 if side == "LONG" else -1
    return {
        "symbol": "BTCUSDT",
        "trigger": {"status": "READY", "side": side, "entry_timeframe": "1h"},
        "confirmation": {"confidence": 64, "score": sign * 64},
        "entry_quality": {"existing_baseline_evidence": {"value": 1}},
        "execution_evidence": {"baseline_source": {"version": "baseline_v1"}},
        "trade_plan": {
            "side": side,
            "entry": 100.0,
            "stop_loss": 100.0 - sign * 2,
            "initial_stop_loss": 100.0 - sign * 2,
            "target1": 100.0 + sign * 4,
            "target2": 100.0 + sign * 6,
            "target1_fraction": 0.75,
            "max_hold_hours": 48,
            "exit_policy": "PAPER_ATR_STRUCTURE_V1",
            "execution_evidence": {"plan_source": {"snapshot_id": 123}},
        },
        "trade_plan_validation": {"is_valid": True, "errors": []},
        "timeframes": [{"timeframe": "1h", "score": sign * 64}],
    }


def _trade(payload, **overrides):
    plan = payload["trade_plan"]
    return SimpleNamespace(**({
        "id": 1,
        "symbol": payload["symbol"],
        "side": plan["side"],
        "entry_price": plan["entry"],
        "stop_loss": plan["stop_loss"],
        "initial_stop_loss": plan["initial_stop_loss"],
        "target1": plan["target1"],
        "target2": plan["target2"],
        "target1_fraction": plan["target1_fraction"],
        "target1_hit_at": None,
        "exit_policy": plan["exit_policy"],
        "max_hold_hours": plan["max_hold_hours"],
        "confidence": 64,
        "risk_reward": 3,
        "opened_at": OPENED_AT,
        "trailing_activation_r": payload.get("trailing_activation_r"),
    } | overrides))


def _mark(price, observed_at=None):
    return SimpleNamespace(
        high_price=price, low_price=price, close_price=price,
        candle_time=observed_at or OPENED_AT + timedelta(minutes=1),
        live_mark=True, source="TEST_MARK",
    )


@pytest.mark.parametrize("definition", EXIT_DEFINITIONS, ids=lambda item: item["id"])
@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_exit_clone_changes_only_execution_metadata(definition, side):
    baseline = _payload(side)
    original = copy.deepcopy(baseline)
    result = build_exit_experiment_payload(baseline, definition)
    assert baseline == original
    expected = copy.deepcopy(original)
    experiment = {
        "entry_quality_profile": "BASELINE_ENTRY_V1",
        "exit_management_profile": "DELAYED_TRAIL_1R_V1",
        "experiment_version": definition["version"],
        "paper_only": True,
    }
    for scope in (expected, expected["trade_plan"]):
        scope["trailing_activation_r"] = 1.0
        scope["execution_evidence"].update(experiment)
    assert result == expected
    result["trigger"]["status"] = "WAIT"
    result["entry_quality"]["existing_baseline_evidence"]["value"] = 2
    result["execution_evidence"]["baseline_source"]["version"] = "modified"
    result["trade_plan"]["execution_evidence"]["plan_source"]["snapshot_id"] = 999
    assert baseline == original


@pytest.mark.parametrize("definition", EXIT_DEFINITIONS, ids=lambda item: item["id"])
@pytest.mark.parametrize("has_plan_key", [True, False])
def test_exit_clone_never_invents_missing_plan_or_rescues_wait(definition, has_plan_key):
    baseline = {"trigger": {"status": "WAIT", "side": None, "reason": "Baseline blocker"}}
    if has_plan_key:
        baseline["trade_plan"] = None
    original = copy.deepcopy(baseline)
    result = build_exit_experiment_payload(baseline, definition)
    assert result["trigger"] == baseline["trigger"]
    assert result.get("trade_plan") is None
    assert ("trade_plan" in result) == has_plan_key
    assert baseline == original


@pytest.mark.parametrize("definition", ENTRY_DEFINITIONS + EXIT_DEFINITIONS, ids=lambda item: item["id"])
def test_each_entry_and_exit_experiment_is_frozen_and_paper_only(definition):
    assert strategy_definition(definition["id"]) is definition
    assert definition["immutable_experiment"] is True
    assert definition["official_execution_enabled"] is False
    assert definition["execution_scope"] == "PAPER_ONLY"
    assert definition["signal_threshold"] == 40.0
    assert definition["full_size_threshold"] == 60.0


def test_entry_cohorts_receive_new_versions_and_baselines_keep_their_versions():
    assert CORE_SIGNAL_ENTRY_STRATEGY["version"] == "core_signal_entry_v1"
    assert MARKET_MOVE_ENTRY_STRATEGY["version"] == "market_move_entry_v2"
    assert MARKET_MOVE_ENTRY_STRATEGY["decision_version"] == "market_move_entry_strategy_v2"
    assert REGIME_TREND_ENTRY_STRATEGY["version"] == "regime_trend_entry_v2"
    assert REGIME_TREND_ENTRY_STRATEGY["decision_version"] == "regime_trend_entry_strategy_v2"
    for baseline in (CORE_SIGNAL_STRATEGY, MARKET_MOVE_STRATEGY, REGIME_TREND_STRATEGY):
        assert baseline["version"] == baseline["id"].lower() + "_v1"
        assert baseline["official_execution_enabled"] is True
        assert "immutable_experiment" not in baseline


@pytest.mark.parametrize("definition", EXIT_DEFINITIONS, ids=lambda item: item["id"])
@pytest.mark.parametrize("repository", [PaperTradeRepository, StrategyShadowTradeRepository])
def test_exit_metadata_survives_existing_ledger_creation(definition, repository):
    baseline = _candidate(definition, 908)
    baseline["execution_evidence"] = {"baseline_source": "retained"}
    original = copy.deepcopy(baseline)
    candidate = build_exit_experiment_payload(baseline, definition)
    with _session() as db:
        row = repository().save_candidate(db, candidate)
        db.expire_all()
        evidence = read_evidence(row.execution_evidence_json)
        assert row.trailing_activation_r == 1.0
        assert row.strategy_id == definition["id"]
        assert row.strategy_version == definition["version"]
        assert evidence["baseline_source"] == "retained"
        assert evidence["entry_quality_profile"] == "BASELINE_ENTRY_V1"
        assert evidence["exit_management_profile"] == "DELAYED_TRAIL_1R_V1"
        assert evidence["experiment_version"] == definition["version"]
        assert evidence["paper_only"] is True
        assert evidence["trailing_activation_r"] == 1.0
    assert baseline == original


@pytest.mark.parametrize("definition", EXIT_DEFINITIONS, ids=lambda item: item["id"])
@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_continuous_trail_starts_at_exact_one_r_not_just_before(definition, side):
    baseline = _payload(side)
    candidate = build_exit_experiment_payload(baseline, definition)
    sign = 1 if side == "LONG" else -1
    activation_price = 100.0 + sign * 2
    just_before = math.nextafter(activation_price, 100.0)
    assert evaluate_paper_trade_exit(_trade(baseline), _mark(just_before))["action"] == "MOVE_STOP"
    assert evaluate_paper_trade_exit(_trade(candidate), _mark(just_before))["action"] == "HOLD"
    at_one_r = evaluate_paper_trade_exit(_trade(candidate), _mark(activation_price))
    assert at_one_r["action"] == "MOVE_STOP"
    assert at_one_r["new_stop_loss"] == 100.0
    assert at_one_r["reason"] == "FAVORABLE_PRICE_TRAIL"
    advanced = _trade(candidate, stop_loss=100.0 + sign)
    assert evaluate_paper_trade_exit(advanced, _mark(100.0 + sign * 2.5))["action"] == "HOLD"


@pytest.mark.parametrize("definition", EXIT_DEFINITIONS, ids=lambda item: item["id"])
@pytest.mark.parametrize("side", ["LONG", "SHORT"])
@pytest.mark.parametrize("gap", [False, True])
def test_initial_hard_stop_remains_inclusive_before_activation(definition, side, gap):
    baseline = _payload(side)
    candidate = build_exit_experiment_payload(baseline, definition)
    sign = 1 if side == "LONG" else -1
    price = baseline["trade_plan"]["stop_loss"] - (sign if gap else 0)
    for payload in (baseline, candidate):
        decision = evaluate_paper_trade_exit(_trade(payload), _mark(price))
        assert decision["action"] == "CLOSE"
        assert decision["fill_profile"]["trigger_type"] == "STOP"


@pytest.mark.parametrize("definition", EXIT_DEFINITIONS, ids=lambda item: item["id"])
@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_t1_partial_protection_and_t2_close_remain_unchanged(definition, side):
    baseline = _payload(side)
    candidate = build_exit_experiment_payload(baseline, definition)
    for payload in (baseline, candidate):
        trade = _trade(payload)
        first = evaluate_paper_trade_exit(trade, _mark(trade.target1))
        assert first["action"] == "PARTIAL_CLOSE"
        assert first["fill_profile"]["trigger_type"] == "TARGET1"
        assert first["remaining_position_fraction"] == 0.25
        assert first["new_stop_loss"] == (trade.entry_price + trade.target1) / 2
        trade.target1_hit_at = OPENED_AT + timedelta(minutes=1)
        trade.stop_loss = first["new_stop_loss"]
        protected = evaluate_paper_trade_exit(trade, _mark(trade.stop_loss))
        assert protected["action"] == "CLOSE"
        assert protected["fill_profile"]["trigger_type"] == "STOP"
        second = evaluate_paper_trade_exit(trade, _mark(trade.target2))
        assert second["action"] == "CLOSE"
        assert second["fill_profile"]["trigger_type"] == "TARGET2"


@pytest.mark.parametrize("definition", EXIT_DEFINITIONS, ids=lambda item: item["id"])
@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_max_hold_deadline_remains_exact_and_precedes_favorable_exits(definition, side):
    baseline = _payload(side)
    candidate = build_exit_experiment_payload(baseline, definition)
    deadline = OPENED_AT + timedelta(hours=48)
    for payload in (baseline, candidate):
        trade = _trade(payload)
        before = _mark(100, deadline - timedelta(microseconds=1))
        assert evaluate_paper_trade_exit(trade, before)["action"] == "HOLD"
        for price in (100, trade.target1, trade.target2):
            decision = evaluate_paper_trade_exit(trade, _mark(price, deadline))
            assert decision["action"] == "CLOSE"
            assert decision["fill_profile"]["trigger_type"] == "TIME_EXIT"
