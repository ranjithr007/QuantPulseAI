import copy
from datetime import datetime, timedelta

import pytest

from app.api.v1 import strategy_api
from app.strategies.learning import strategy_definitions
from app.strategies.registry import STRATEGY_REGISTRY
from test_frozen_experiment_admission import _row
from test_strategy_attribution import _session_factory


@pytest.mark.parametrize("strategy_id", ["MARKET_MOVE_ENTRY", "REGIME_TREND_ENTRY"])
def test_retired_entry_open_position_and_history_remain_visible_separate_from_v2(monkeypatch, strategy_id):
    factory = _session_factory()
    original_registry = copy.deepcopy(STRATEGY_REGISTRY)
    old_version, current_version = strategy_id.lower() + "_v1", strategy_id.lower() + "_v2"
    with factory() as db:
        open_trade = _row(db, strategy_id, old_version)
        open_id = open_trade.id
        closed = _row(
            db, strategy_id, old_version, plan_id=2, status="CLOSED",
            created_at=datetime.utcnow() - timedelta(days=90),
            closed_at=datetime.utcnow() - timedelta(days=90), realized_pnl_inr=-321,
        )
        closed_id = closed.id
        _row(db, strategy_id, current_version, plan_id=3, status="CLOSED",
             closed_at=datetime.utcnow(), realized_pnl_inr=123)
        assert [item["version"] for item in strategy_definitions(db, strategy_id)] == [current_version]
    monkeypatch.setattr(strategy_api, "SessionLocal", factory)

    summary = strategy_api.get_strategy_summary(strategy_id=strategy_id, since_days=30, candidate_limit=24)
    by_version = {item["version"]: item for item in summary["records"]}
    assert set(by_version) == {old_version, current_version}
    old, current = by_version[old_version], by_version[current_version]
    assert old["read_only"] is old["historical"] is True
    assert old["strategy_type"] == "HISTORICAL"
    assert old["status"] == "RETIRED"
    assert old["name"].endswith("(v1 history)")
    assert old["official_execution_enabled"] is old["paper_execution_enabled"] is False
    assert old["candidates"] == []
    assert old["forward_test_readiness"]["status"] == "HISTORICAL_READ_ONLY"
    assert old["forward_test_readiness"]["promotion_candidate"] is False
    assert old["strategy_paper_wallet"]["open_position_count"] == 1
    assert old["strategy_paper_lifetime_performance"]["net_pnl_inr"] == -321
    assert current["strategy_paper_wallet"]["open_position_count"] == 0
    assert current["strategy_paper_lifetime_performance"]["net_pnl_inr"] == 123
    assert current.get("read_only") is not True
    assert {item["id"] for item in old["strategy_paper_history"]} == {open_id, closed_id}
    assert summary["comparison"]["ranking"] == [strategy_id]

    ledger = strategy_api.get_strategy_ledger(strategy_id=strategy_id, history_limit=20)
    ledger_by_version = {item["version"]: item for item in ledger["records"]}
    assert set(ledger_by_version) == {old_version, current_version}
    assert ledger_by_version[old_version]["read_only"] is True
    assert ledger_by_version[old_version]["strategy_paper_wallet"]["open_position_count"] == 1
    assert ledger_by_version[old_version]["strategy_paper_lifetime_performance"]["net_pnl_inr"] == -321
    assert ledger_by_version[current_version]["strategy_paper_lifetime_performance"]["net_pnl_inr"] == 123
    assert STRATEGY_REGISTRY == original_registry
    with factory() as db:
        assert [item["version"] for item in strategy_definitions(db, strategy_id)] == [current_version]


@pytest.mark.parametrize("strategy_id", [None, "MARKET_MOVE_ENTRY", "REGIME_TREND_ENTRY"])
def test_retired_entry_cohort_does_not_add_empty_cards_without_actual_history(monkeypatch, strategy_id):
    factory = _session_factory()
    monkeypatch.setattr(strategy_api, "SessionLocal", factory)
    summary = strategy_api.get_strategy_summary(strategy_id=strategy_id, since_days=30, candidate_limit=24, include_ledger=False)
    ledger = strategy_api.get_strategy_ledger(strategy_id=strategy_id, history_limit=20)
    expected = len(STRATEGY_REGISTRY) if strategy_id is None else 1
    assert summary["strategy_count"] == ledger["strategy_count"] == expected
    assert all(item.get("read_only") is not True for item in summary["records"] + ledger["records"])
