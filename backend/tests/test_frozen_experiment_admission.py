from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.api.v1.paper_trade_api import _execute_strategy_shadow_candidates
from app.database.models.strategy_shadow_trade import StrategyShadowTrade
from app.database.sqlserver import Base
from app.paper_trading.reentry_policy import same_side_stop_reentry_cooldown
from app.repositories.strategy_shadow_trade_repository import StrategyShadowTradeRepository
from app.strategies.registry import STRATEGY_REGISTRY
from test_strategy_shadow_trading import _automation, _candidate, _session


FROZEN_IDS = [
    "CORE_SIGNAL_ENTRY", "CORE_SIGNAL_EXIT", "MARKET_MOVE_ENTRY",
    "MARKET_MOVE_EXIT", "REGIME_TREND_ENTRY", "REGIME_TREND_EXIT",
]
UPGRADED_ENTRY_IDS = ["MARKET_MOVE_ENTRY", "REGIME_TREND_ENTRY"]


def _row(db, strategy_id, version, *, plan_id=1, **overrides):
    values = {
        "trade_plan_id": plan_id, "risk_decision_id": plan_id + 100,
        "symbol": "BTCUSDT", "side": "LONG", "strategy_id": strategy_id,
        "strategy_version": version, "strategy_decision_snapshot_id": plan_id + 200,
        "entry_price": 100, "initial_stop_loss": 99.25, "stop_loss": 99.25,
        "target1": 101.5, "target2": 102.3, "entry_timeframe": "1h",
        "status": "OPEN", "exit_policy": "PAPER_STAGED_EXIT_V2",
        "opened_at": datetime.utcnow() - timedelta(hours=1),
        "position_notional_inr": 100_000, "margin_used_inr": 20_000,
        "leverage": 5, "remaining_position_fraction": 1.0,
    }
    row = StrategyShadowTrade(**(values | overrides))
    db.add(row)
    db.commit()
    return row


@pytest.mark.parametrize("strategy_id", FROZEN_IDS)
@pytest.mark.parametrize("dialect", ["postgresql", "mssql"])
def test_numbered_frozen_revisions_share_lock_but_auto_and_baseline_books_do_not(strategy_id, dialect):
    db = Mock()
    db.get_bind.return_value.dialect.name = dialect
    db.execute.return_value.scalar.return_value = 0
    repo = StrategyShadowTradeRepository()

    def lock_key(key, version):
        repo.acquire_book_execution_lock(db, key, version)
        return db.execute.call_args.args[1]

    original = lock_key(strategy_id, strategy_id.lower() + "_v1")
    assert lock_key(strategy_id, strategy_id.lower() + "_v2") == original
    assert lock_key(strategy_id, strategy_id.lower() + "_auto_m30_1") != original
    assert lock_key(strategy_id, strategy_id.lower() + "_v1_candidate_test") != original
    baseline_id = strategy_id.rsplit("_", 1)[0]
    baseline = lock_key(baseline_id, baseline_id.lower() + "_v1")
    assert baseline != original
    assert lock_key(baseline_id, baseline_id.lower() + "_v2") != baseline


@pytest.mark.parametrize("strategy_id", FROZEN_IDS)
def test_open_position_guard_spans_only_numbered_revisions_of_same_experiment(strategy_id):
    with _session() as db:
        repo = StrategyShadowTradeRepository()
        old = strategy_id.lower() + "_v1"
        current = strategy_id.lower() + "_v2"
        _row(db, strategy_id, old)
        assert repo.has_open_trade(db, strategy_id, current, "BTCUSDT")
        assert not repo.has_open_trade(db, strategy_id, current, "ETHUSDT")
        assert not repo.has_open_trade(db, strategy_id, strategy_id.lower() + "_auto_m30_1", "BTCUSDT")
        baseline = strategy_id.rsplit("_", 1)[0]
        assert not repo.has_open_trade(db, baseline, baseline.lower() + "_v1", "BTCUSDT")


def test_auto_candidate_open_position_does_not_consume_frozen_or_other_auto_book():
    with _session() as db:
        repo = StrategyShadowTradeRepository()
        strategy_id = "REGIME_TREND_ENTRY"
        _row(db, strategy_id, "regime_trend_entry_auto_m30_1")
        assert not repo.has_open_trade(db, strategy_id, "regime_trend_entry_v2", "BTCUSDT")
        assert not repo.has_open_trade(db, strategy_id, "regime_trend_entry_auto_m30_2", "BTCUSDT")
        assert repo.has_open_trade(db, strategy_id, "regime_trend_entry_auto_m30_1", "BTCUSDT")


def test_frozen_admission_does_not_merge_versioned_risk_valuation_or_performance():
    with _session() as db:
        repo = StrategyShadowTradeRepository()
        strategy_id = "REGIME_TREND_ENTRY"
        old = _row(db, strategy_id, "regime_trend_entry_v1")
        current = _row(
            db, strategy_id, "regime_trend_entry_v2", plan_id=2,
            status="CLOSED", closed_at=datetime.utcnow(), realized_pnl_inr=123,
        )
        assert repo.has_open_trade(db, strategy_id, "regime_trend_entry_v2", "BTCUSDT")
        history = repo.risk_snapshot_trades(
            db, window_start=datetime.utcnow() - timedelta(days=1),
            strategy_id=strategy_id, strategy_version="regime_trend_entry_v2",
        )
        assert [row.id for row in history] == [current.id]
        assert [row.id for row in repo.all_trades(
            db, strategy_id=strategy_id, strategy_version="regime_trend_entry_v1",
        )] == [old.id]
        snapshot = repo.valuation_snapshot(
            db, strategy_id=strategy_id, strategy_version="regime_trend_entry_v2",
        )
        assert snapshot["open_trades"] == []
        assert snapshot["realized_pnl_inr"] == 123
        pnl = repo.realized_pnl_by_strategy(db, {(strategy_id, "regime_trend_entry_v2")})
        assert pnl == {(strategy_id, "regime_trend_entry_v2"): 123}


@pytest.mark.parametrize("strategy_id", UPGRADED_ENTRY_IDS)
@pytest.mark.parametrize("closed_minutes,old_side,exit_reason,blocked", [
    (10, "LONG", "STOP", True),
    (10, "SHORT", "STOP", False),
    (10, "LONG", "TARGET2", False),
    (30, "LONG", "STOP", False),
])
def test_frozen_cooldown_spans_versions_without_changing_direction_or_boundary(
    strategy_id, closed_minutes, old_side, exit_reason, blocked,
):
    with _session() as db:
        now = datetime.now(timezone.utc)
        _row(
            db, strategy_id, strategy_id.lower() + "_v1", side=old_side,
            status="CLOSED", exit_reason=exit_reason,
            closed_at=(now - timedelta(minutes=closed_minutes)).replace(tzinfo=None),
        )
        history = StrategyShadowTradeRepository().stop_reentry_history(
            db, strategy_id=strategy_id, strategy_version=strategy_id.lower() + "_v2",
            symbol="BTCUSDT", side="LONG", window_start=(now - timedelta(minutes=30)).replace(tzinfo=None),
            versioned_history=[],
        )
        cooldown = same_side_stop_reentry_cooldown(history, "BTCUSDT", "LONG", now=now)
        assert cooldown["active"] is blocked


def test_auto_candidate_stop_does_not_start_frozen_cooldown_or_query_other_auto_books():
    with _session() as db:
        repo = StrategyShadowTradeRepository()
        now = datetime.utcnow()
        _row(
            db, "REGIME_TREND_ENTRY", "regime_trend_entry_auto_m30_1",
            status="CLOSED", exit_reason="STOP", closed_at=now,
        )
        original_history = []
        kwargs = dict(
            strategy_id="REGIME_TREND_ENTRY", symbol="BTCUSDT", side="LONG",
            window_start=now - timedelta(minutes=30), versioned_history=original_history,
        )
        assert repo.stop_reentry_history(db, strategy_version="regime_trend_entry_v2", **kwargs) == []
        assert repo.stop_reentry_history(db, strategy_version="regime_trend_entry_auto_m30_2", **kwargs) is original_history


@pytest.mark.parametrize("strategy_id", UPGRADED_ENTRY_IDS)
@pytest.mark.parametrize("status,action", [
    ("OPEN", "skipped_existing_open_shadow_trade"),
    ("CLOSED", "skipped_shadow_same_side_stop_cooldown"),
])
def test_executor_rejects_upgrade_duplicate_and_immediate_post_stop_reentry(strategy_id, status, action):
    with _session() as db:
        _row(
            db, strategy_id, strategy_id.lower() + "_v1", status=status,
            closed_at=datetime.utcnow() - timedelta(minutes=10) if status == "CLOSED" else None,
            exit_reason="STOP" if status == "CLOSED" else None,
        )
        candidate = _candidate(STRATEGY_REGISTRY[strategy_id], 42)
        with patch("app.api.v1.paper_trade_api._current_paper_entry_mark") as mark:
            result = _execute_strategy_shadow_candidates(db, [candidate], _automation())
        assert result["executed_count"] == 0
        assert [item["action"] for item in result["skipped"]] == [action]
        mark.assert_not_called()
        assert db.query(StrategyShadowTrade).count() == 1


@pytest.mark.parametrize("strategy_id", UPGRADED_ENTRY_IDS)
def test_executor_opens_new_revision_after_prior_stop_cooldown_expires(strategy_id):
    with _session() as db:
        _row(
            db, strategy_id, strategy_id.lower() + "_v1", status="CLOSED", exit_reason="STOP",
            closed_at=datetime.utcnow() - timedelta(minutes=31), realized_pnl_inr=-1_000_000,
        )
        candidate = _candidate(STRATEGY_REGISTRY[strategy_id], 42)
        mark = {"symbol": "BTCUSDT", "mark_price": 100, "observed_at": datetime.now(timezone.utc), "source": "TEST_MARK"}
        auto = _automation() | {"dailyLossLimitEnabled": True}
        with patch("app.api.v1.paper_trade_api._current_paper_entry_mark", return_value=mark):
            result = _execute_strategy_shadow_candidates(db, [candidate], auto)
        assert result["executed_count"] == 1, result
        assert result["executed"][0]["strategy_version"] == STRATEGY_REGISTRY[strategy_id]["version"]


def test_sqlite_frozen_revision_reservation_serializes_independent_connections(tmp_path):
    engine = create_engine(
        "sqlite:///" + (tmp_path / "frozen-admission.sqlite").as_posix(),
        connect_args={"timeout": 0},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    repo = StrategyShadowTradeRepository()
    try:
        with factory() as first, factory() as second:
            # Existing read transactions do not cause a nested-BEGIN failure.
            assert first.query(StrategyShadowTrade).count() == 0
            repo.acquire_book_execution_lock(first, "MARKET_MOVE_ENTRY", "market_move_entry_v1")
            reservation = first.get_transaction()
            repo.acquire_book_execution_lock(first, "MARKET_MOVE_ENTRY", "market_move_entry_v1")
            assert first.get_transaction() is reservation
            with pytest.raises(OperationalError, match="locked"):
                repo.acquire_book_execution_lock(second, "MARKET_MOVE_ENTRY", "market_move_entry_v2")
            second.rollback()
            first.rollback()
            repo.acquire_book_execution_lock(second, "MARKET_MOVE_ENTRY", "market_move_entry_v2")
            assert second.query(StrategyShadowTrade).count() == 0
    finally:
        engine.dispose()
