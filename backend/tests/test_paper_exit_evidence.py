from datetime import datetime, timedelta, timezone
from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import Mock

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text

from app.database.models.paper_trade import PaperTrade
from app.database.models.strategy_shadow_trade import StrategyShadowTrade
from app.jobs import paper_trade_fast_exit_job as job
from app.paper_trading.exit_evidence import classify_exit, entry_evidence_fields, read_evidence
from app.paper_trading.paper_trade_monitor import evaluate_paper_trade_exit
from app.repositories.paper_trade_repository import PaperTradeRepository
from app.repositories.strategy_shadow_trade_repository import StrategyShadowTradeRepository
from app.strategies.registry import STRATEGY_REGISTRY
from test_paper_fast_exits import runtime, add_trade, tick
from test_strategy_shadow_trading import _session, _candidate


def trade(side="LONG", **overrides):
    sign = 1 if side == "LONG" else -1
    values = dict(id=1, symbol="BTCUSDT", side=side, entry_price=100., initial_stop_loss=100-sign*.75,
        stop_loss=100-sign*.75, target1=100+sign*1.5, target2=100+sign*2.3, target1_hit_at=None,
        exit_policy="PAPER_ATR_STRUCTURE_V1", confidence=60, risk_reward=2, max_hold_hours=48,
        opened_at=datetime.utcnow(), trailing_activation_r=None)
    values.update(overrides)
    return N(**values)


def candle(price, **overrides):
    return N(**(dict(high_price=price, low_price=price, close_price=price, candle_time=datetime.utcnow(), live_mark=True, source="TEST_MARK") | overrides))


@pytest.mark.parametrize("side,early,activation,stop", [("LONG", 100.5,100.75,99.25), ("SHORT",99.5,99.25,100.75)])
def test_delayed_challenger_preserves_hard_stop_and_legacy_trail(side, early, activation, stop):
    baseline = trade(side)
    challenger = trade(side, trailing_activation_r=1.0)
    assert evaluate_paper_trade_exit(baseline, candle(early))["action"] == "MOVE_STOP"
    assert evaluate_paper_trade_exit(challenger, candle(early))["action"] == "HOLD"
    at_r = evaluate_paper_trade_exit(challenger, candle(activation))
    assert at_r["action"] == "MOVE_STOP"
    assert at_r["new_stop_loss"] == 100
    assert evaluate_paper_trade_exit(challenger, candle(stop))["fill_profile"]["trigger_type"] == "STOP"


def test_deadline_precedes_favorable_trailing_and_targets():
    item = trade(opened_at=datetime.utcnow()-timedelta(hours=49))
    for price in (100.5, 103):
        assert evaluate_paper_trade_exit(item, candle(price))["fill_profile"]["trigger_type"] == "TIME_EXIT"


@pytest.mark.parametrize("side,active,initial,hit,expected", [
    ("LONG",99.25,99.25,None,"INITIAL_STOP"),
    ("SHORT",100.75,100.75,None,"INITIAL_STOP"),
    ("LONG",100.05,99.25,None,"TRAILED_STOP_PRE_T1"),
    ("SHORT",99.95,100.75,None,"TRAILED_STOP_PRE_T1"),
    ("LONG",100.75,99.25,datetime(2026,9,7),"PROTECTED_STOP_AFTER_T1"),
    ("LONG",99.25,None,None,"UNKNOWN_STOP"),
    ("LONG",98,99.25,None,"UNKNOWN_STOP"),
])
def test_stop_classification_does_not_confuse_net_outcome(side,active,initial,hit,expected):
    assert classify_exit(trade(side,stop_loss=active,initial_stop_loss=initial,target1_hit_at=hit),"STOP") == expected


@pytest.mark.parametrize("repository", [PaperTradeRepository, StrategyShadowTradeRepository])
def test_entry_cohort_metadata_and_activation_are_persisted(repository):
    candidate = _candidate(next(iter(STRATEGY_REGISTRY.values())),902)
    candidate.update(trailing_activation_r=1., execution_evidence={"experiment_version":"test_exit_v1","exit_management_profile":"DELAYED_TRAIL_1R_V1"})
    with _session() as db:
        result = repository().save_candidate(db,candidate)
        assert result.trailing_activation_r == 1
        evidence = read_evidence(result.execution_evidence_json)
        assert evidence["experiment_version"] == "test_exit_v1"
        assert evidence["strategy_version"] == candidate["trade_plan"]["strategy_version"]


@pytest.mark.parametrize("value", [float("nan"),float("inf"),-1,6])
def test_invalid_activation_fails_closed(value):
    with pytest.raises(ValueError):
        entry_evidence_fields({"trailing_activation_r":value})


def test_entry_evidence_is_bounded():
    with pytest.raises(ValueError,match="bounded"):
        entry_evidence_fields({"execution_evidence":{"large":"x"*9000}})


@pytest.mark.parametrize("model", [PaperTrade, StrategyShadowTrade])
def test_final_trigger_and_observed_excursions_survive_both_books(runtime, model):
    factory,feed = runtime
    key=add_trade(factory,model)
    now=datetime.now(timezone.utc)-timedelta(seconds=1)
    feed.ingest([tick(100.8,now)])
    assert job.run_paper_trade_fast_exit_job()["stop_moves"] == 1
    feed.ingest([tick(100.05,now+timedelta(milliseconds=50))])
    result = job.run_paper_trade_fast_exit_job()
    assert result["closed"] == 1, result
    with factory() as db:
        row=db.get(model,key)
        evidence=read_evidence(row.exit_evidence_json)
        assert evidence["classification"] == "TRAILED_STOP_PRE_T1"
        assert evidence["active_stop_before_trigger"] == 100.05
        assert evidence["initial_stop_loss"] == 99.25
        assert evidence["trigger_type"] == "STOP"
        assert evidence["source"] == "BINANCE_MARK_STREAM_1S"
        assert evidence["observed_at"] and evidence["processed_at"]
        assert evidence["observations"]["mfe_percent"] == .8
        assert evidence["observations"]["coverage"] == "OBSERVED_ONLY"
        assert row.result == "LOSS"


def test_hold_excursion_writes_are_checkpointed_not_per_tick(runtime):
    factory,feed=runtime
    key=add_trade(factory,PaperTrade,trailing_activation_r=1.)
    now=datetime.now(timezone.utc)-timedelta(seconds=1)
    feed.ingest([tick(100.1,now)])
    first_result = job.run_paper_trade_fast_exit_job()
    assert first_result["status"] == "OK", first_result
    with factory() as db:
        before=db.get(PaperTrade,key).exit_evidence_json
    feed.ingest([tick(100.2,now+timedelta(milliseconds=50))])
    second_result = job.run_paper_trade_fast_exit_job()
    assert second_result["status"] == "OK", second_result
    with factory() as db:
        assert db.get(PaperTrade,key).exit_evidence_json == before
    feed.ingest([tick(99.25,now+timedelta(milliseconds=100))])
    close_result = job.run_paper_trade_fast_exit_job()
    assert close_result["closed"] == 1, close_result
    with factory() as db:
        evidence=read_evidence(db.get(PaperTrade,key).exit_evidence_json)
        assert evidence["observations"]["mfe_percent"] == .2
        assert evidence["observations"]["mae_percent"] == .75


def test_closed_history_orders_by_close_time_not_entry_time():
    with _session() as db:
        now=datetime.utcnow()
        first=PaperTrade(symbol="BTCUSDT",status="CLOSED",created_at=now-timedelta(days=1),closed_at=now)
        second=PaperTrade(symbol="ETHUSDT",status="CLOSED",created_at=now,closed_at=now-timedelta(hours=1))
        db.add_all([first,second]);db.commit()
        rows=PaperTradeRepository().list_trades(db,status="CLOSED")
        assert [row.symbol for row in rows][:2] == ["BTCUSDT","ETHUSDT"]


def test_strategy_book_lock_is_shared_across_coins_but_version_scoped():
    db=Mock()
    db.get_bind.return_value.dialect.name="postgresql"
    repo=StrategyShadowTradeRepository()
    repo.acquire_book_execution_lock(db,"MARKET_MOVE_EXIT","v1")
    first=db.execute.call_args.args[1]["lock_key"]
    repo.acquire_book_execution_lock(db,"MARKET_MOVE_EXIT","v1")
    assert db.execute.call_args.args[1]["lock_key"] == first
    repo.acquire_book_execution_lock(db,"MARKET_MOVE_EXIT","v2")
    assert db.execute.call_args.args[1]["lock_key"] != first


def test_strategy_book_lock_checks_sql_server_lock_failure():
    db=Mock()
    db.get_bind.return_value.dialect.name="mssql"
    db.execute.return_value.scalar.return_value=-1
    with pytest.raises(RuntimeError,match="book execution lock"):
        StrategyShadowTradeRepository().acquire_book_execution_lock(db,"MARKET_MOVE_EXIT","v1")


@pytest.mark.parametrize("repository", [PaperTradeRepository, StrategyShadowTradeRepository])
def test_sqlite_schema_checks_preserve_initialized_execution_transaction(repository):
    with _session() as db:
        repo=repository()
        repo.ensure_table(db)
        db.rollback()
        reservation=db.begin()
        repo.ensure_table(db)
        repo.ensure_table(db)
        assert db.get_transaction() is reservation
        assert reservation.is_active


def test_migration_preserves_existing_positions_and_is_idempotent():
    path=Path(__file__).resolve().parents[1]/"alembic"/"versions"/"x2p3q4r5s6t7_add_paper_execution_evidence.py"
    spec=spec_from_file_location("test_paper_evidence_migration",path)
    migration=module_from_spec(spec);spec.loader.exec_module(migration)
    engine=create_engine("sqlite://")
    with engine.begin() as connection:
        for table in ("paper_trades","strategy_shadow_trades"):
            connection.execute(text(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY,status TEXT,closed_at DATETIME,stop_loss FLOAT)"))
            connection.execute(text(f"INSERT INTO {table} (id,status,stop_loss) VALUES (1,'OPEN',99.25)"))
        migration.op=Operations(MigrationContext.configure(connection))
        migration.upgrade();migration.upgrade()
        for table in ("paper_trades","strategy_shadow_trades"):
            row=connection.execute(text(f"SELECT stop_loss,trailing_activation_r,execution_evidence_json,exit_evidence_json FROM {table}")).one()
            assert tuple(row)==(99.25,None,None,None)
        assert "ix_paper_trades_closed_history" in {item["name"] for item in inspect(connection).get_indexes("paper_trades")}
