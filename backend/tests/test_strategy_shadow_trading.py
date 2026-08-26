from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1.paper_trade_api import _execute_strategy_shadow_candidates
from app.database.models.paper_trade import PaperTrade
from app.database.models.strategy_shadow_trade import StrategyShadowTrade
from app.database.sqlserver import Base
from app.jobs.paper_trade_monitor_job import _run_strategy_shadow_monitor
from app.paper_trading.fill_model import build_fill_profile
from app.paper_trading.inr_sizing import build_inr_paper_sizing
from app.strategies.registry import STRATEGY_REGISTRY


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _automation():
    return {
        "enabled": True,
        "locked": False,
        "emergencyStop": False,
        "allowedSymbols": ["BTCUSDT"],
        "maxRiskPerTrade": 1.0,
        "maxRiskPerTradeEnabled": False,
        "maxLeverage": 5,
        "maxPositionSize": 1_000_000.0,
        "minConfidence": 40.0,
        "direction": "BOTH",
        "executionMode": "PAPER",
        "liveExecutionEnabled": False,
    }


def _candidate(definition, plan_id):
    plan = {
        "id": plan_id,
        "symbol": "BTCUSDT",
        "side": "LONG",
        "entry_price": 100.0,
        "stop_loss": 99.25,
        "target1": 101.5,
        "target2": 102.3,
        "risk_reward": 2.1,
        "confidence": 64.0,
        "entry_timeframe": "1h",
        "timeframe_stack": "1h,2h,4h,1d",
        "strategy_id": definition["id"],
        "strategy_version": definition["version"],
        "strategy_decision_snapshot_id": plan_id + 100,
    }
    risk = {
        "id": plan_id + 200,
        "trade_plan_id": plan_id,
        "decision": "APPROVE",
        "signal": "LONG",
        "entry_price": 100.0,
        "stop_loss": 99.25,
        "target1": 101.5,
        "target2": 102.3,
        "risk_reward": 2.1,
        "position_size": 1.0,
        "risk_percent": 1.0,
        "confidence": 64.0,
        "strategy_id": definition["id"],
        "strategy_version": definition["version"],
        "strategy_decision_snapshot_id": plan_id + 100,
    }
    return {
        "symbol": "BTCUSDT",
        "side": "LONG",
        "eligible": False,
        "blocked_reasons": ["Active trade already exists for this coin"],
        "blocker_scopes": {
            "trade": [],
            "coin": ["Active trade already exists for this coin"],
            "account": [],
        },
        "trade_plan": plan,
        "risk_decision": risk,
        "fill_profile": build_fill_profile(
            side="LONG",
            planned_entry_price=100.0,
            stop_loss=99.25,
            target1=102.3,
            confidence=64.0,
            risk_reward=2.1,
        ),
        "paper_sizing": build_inr_paper_sizing(64.0),
        "market_context": {},
        "validation_contract_version": "shadow-test-v1",
    }


def test_every_strategy_opens_one_shadow_trade_while_official_lock_is_isolated():
    db = _session()
    candidates = [
        _candidate(definition, index)
        for index, definition in enumerate(STRATEGY_REGISTRY.values(), start=1)
    ]
    mark = {
        "symbol": "BTCUSDT",
        "mark_price": 100.0,
        "observed_at": datetime.now(timezone.utc),
        "source": "TEST_MARK",
    }
    try:
        with patch(
            "app.api.v1.paper_trade_api._current_paper_entry_mark",
            return_value=mark,
        ):
            first = _execute_strategy_shadow_candidates(db, candidates, _automation())
            duplicate = _execute_strategy_shadow_candidates(
                db,
                candidates,
                _automation(),
            )

        assert first["executed_count"] == len(STRATEGY_REGISTRY)
        assert duplicate["executed_count"] == 0
        assert {
            item.strategy_id
            for item in db.query(StrategyShadowTrade).filter(
                StrategyShadowTrade.status == "OPEN"
            )
        } == set(STRATEGY_REGISTRY)
        assert db.query(PaperTrade).count() == 0
    finally:
        db.close()


def test_shadow_monitor_applies_target1_then_target2_and_records_net_result():
    db = _session()
    definition = next(iter(STRATEGY_REGISTRY.values()))
    candidate = _candidate(definition, 10)
    mark = {
        "symbol": "BTCUSDT",
        "mark_price": 100.0,
        "observed_at": datetime.now(timezone.utc),
        "source": "TEST_MARK",
    }
    try:
        with patch(
            "app.api.v1.paper_trade_api._current_paper_entry_mark",
            return_value=mark,
        ):
            result = _execute_strategy_shadow_candidates(
                db,
                [candidate],
                _automation(),
            )
        assert result["executed_count"] == 1
        trade = db.query(StrategyShadowTrade).one()
        base = trade.opened_at + timedelta(minutes=5)
        candles = [
            SimpleNamespace(
                high_price=trade.target1,
                low_price=trade.stop_loss + 0.1,
                close_price=trade.target1,
                candle_time=base,
                open_time=base - timedelta(minutes=5),
                close_time=base,
            ),
            SimpleNamespace(
                high_price=trade.target2,
                low_price=trade.target1,
                close_price=trade.target2,
                candle_time=base + timedelta(minutes=5),
                open_time=base,
                close_time=base + timedelta(minutes=5),
            ),
        ]
        with patch(
            "app.jobs.paper_trade_monitor_job._exit_candles",
            return_value=(candles, "5m", False, True),
        ):
            summary = _run_strategy_shadow_monitor(db)

        db.refresh(trade)
        assert summary["partial_closes"] == 1
        assert summary["closed"] == 1
        assert trade.status == "CLOSED"
        assert trade.result == "WIN"
        assert trade.remaining_position_fraction == 0.25
        assert trade.pnl_percent > 0
        assert trade.realized_pnl_inr > 0
    finally:
        db.close()


def test_database_rejects_two_open_shadow_positions_for_same_strategy_and_coin():
    db = _session()
    definition = next(iter(STRATEGY_REGISTRY.values()))

    def row(plan_id):
        return StrategyShadowTrade(
            trade_plan_id=plan_id,
            risk_decision_id=plan_id,
            symbol="BTCUSDT",
            side="LONG",
            strategy_id=definition["id"],
            strategy_version=definition["version"],
            strategy_decision_snapshot_id=plan_id,
            entry_price=100.0,
            stop_loss=99.25,
            initial_stop_loss=99.25,
            target1=101.5,
            target2=102.3,
            entry_timeframe="1h",
            status="OPEN",
        )

    try:
        db.add(row(1))
        db.commit()
        db.add(row(2))
        try:
            db.commit()
            raise AssertionError("Expected the shadow strategy-symbol lock to fail")
        except IntegrityError:
            db.rollback()
    finally:
        db.close()
