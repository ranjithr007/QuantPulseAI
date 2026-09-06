from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.sqlserver import Base
from app.database.models.paper_trade import PaperTrade
from app.database.models.strategy_shadow_trade import StrategyShadowTrade
from app.database.models.app_notification import AppNotification
from app.jobs import paper_trade_fast_exit_job as job
from app.jobs.paper_trade_monitor_job import _predates_live_protection
from app.paper_trading.exit_lock import lock_open_trade, advance_exit_checkpoint
from app.scheduler.registry import get_job_definition
from app.services.paper_exit_prices import PaperExitPrices, STREAM_URL


def test_fast_schedule_is_one_second_isolated_and_non_overlapping():
    kwargs = get_job_definition("paper_trade_fast_exit").schedule_kwargs()
    assert kwargs["seconds"] == 1
    assert kwargs["max_instances"] == 1
    assert kwargs["coalesce"] is True
    assert kwargs["executor"] == "paper_exits"
    assert STREAM_URL == "wss://fstream.binance.com/market/ws/!markPrice@arr@1s"


def tick(price, now, symbol="BTCUSDT"):
    return {"s": symbol, "p": str(price), "E": int(now.timestamp() * 1000)}


def test_stream_retains_crossing_tick_and_deduplicates_out_of_order_frames():
    feed = PaperExitPrices()
    now = datetime.now(timezone.utc)
    feed.ingest([tick(98, now - timedelta(seconds=1))], now)
    feed.ingest([tick(100, now)], now)
    feed.ingest([tick(97, now - timedelta(seconds=1))], now)
    assert [m["mark_price"] for m in feed.take(["BTCUSDT"], now)["BTCUSDT"]] == [98, 100]
    assert [m["mark_price"] for m in feed.take(["BTCUSDT"], now)["BTCUSDT"]] == [100]


@pytest.mark.parametrize("price,offset", [("nan", 0), ("inf", 0), (0, 0), (-1, 0), (100, -10), (100, 10)])
def test_stream_rejects_invalid_stale_and_future_quotes(price, offset):
    feed = PaperExitPrices()
    now = datetime.now(timezone.utc)
    feed.ingest([tick(price, now + timedelta(seconds=offset)), {}], now)
    assert feed.take(["BTCUSDT"], now)["BTCUSDT"] == []


@pytest.fixture
def runtime(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    feed = PaperExitPrices()
    feed.start = Mock()
    monkeypatch.setattr(job, "SessionLocal", factory)
    monkeypatch.setattr(job, "paper_exit_prices", feed)
    monkeypatch.setattr(job, "_alerted", {})
    yield factory, feed
    engine.dispose()


def add_trade(factory, model, side="LONG", **overrides):
    sign = 1 if side == "LONG" else -1
    values = dict(symbol="BTCUSDT", side=side, entry_price=100,
        stop_loss=100 - sign * .75, initial_stop_loss=100 - sign * .75,
        target1=100 + sign * 1.5, target2=100 + sign * 2.3,
        strategy_id="core_signal", strategy_version="v1", strategy_decision_snapshot_id=1,
        trade_plan_id=1, risk_decision_id=1, entry_timeframe="1h", status="OPEN",
        exit_policy="PAPER_STAGED_EXIT_V2", target1_fraction=.75, remaining_position_fraction=1,
        max_hold_hours=48, confidence=70, risk_reward=2, fee_bps=7.5,
        position_notional_inr=150000, margin_used_inr=30000, leverage=5,
        opened_at=datetime.utcnow() - timedelta(minutes=1))
    values.update(overrides)
    with factory() as db:
        row = model(**values)
        db.add(row)
        db.commit()
        return row.id


@pytest.mark.parametrize("model", [PaperTrade, StrategyShadowTrade])
@pytest.mark.parametrize("side,price", [("LONG", 99.25), ("SHORT", 100.75)])
def test_stop_inclusive_both_books_without_waiting_for_candles(runtime, model, side, price):
    factory, feed = runtime
    key = add_trade(factory, model, side)
    feed.ingest([tick(price, datetime.now(timezone.utc))])
    assert job.run_paper_trade_fast_exit_job()["closed"] == 1
    assert job.run_paper_trade_fast_exit_job()["closed"] == 0
    with factory() as db:
        row = db.get(model, key)
        assert row.status == "CLOSED"
        assert row.exit_reason == "STOP"


@pytest.mark.parametrize("model", [PaperTrade, StrategyShadowTrade])
@pytest.mark.parametrize("side,price", [("LONG", 103), ("SHORT", 97)])
def test_both_targets_close_in_one_tick(runtime, model, side, price):
    factory, feed = runtime
    key = add_trade(factory, model, side)
    feed.ingest([tick(price, datetime.now(timezone.utc))])
    result = job.run_paper_trade_fast_exit_job()
    assert result["partial_closes"] == result["closed"] == 1
    with factory() as db:
        row = db.get(model, key)
        assert row.exit_reason == "TARGET2"
        assert row.target1_fraction == .75
        assert row.target1_hit_at is not None


def test_stale_feed_keeps_honest_open_state_and_alerts_without_spam(runtime):
    factory, feed = runtime
    key = add_trade(factory, PaperTrade)
    feed.ingest([tick(97, datetime.now(timezone.utc) - timedelta(seconds=20))])
    assert job.run_paper_trade_fast_exit_job()["status"] == "DEGRADED"
    job.run_paper_trade_fast_exit_job()
    with factory() as db:
        assert db.get(PaperTrade, key).status == "OPEN"
        assert db.query(AppNotification).count() == 1


def test_tick_before_entry_cannot_close_a_new_position(runtime):
    factory, feed = runtime
    add_trade(factory, PaperTrade, opened_at=datetime.utcnow() + timedelta(seconds=1))
    feed.ingest([tick(90, datetime.now(timezone.utc))])
    assert job.run_paper_trade_fast_exit_job()["closed"] == 0


@pytest.mark.parametrize("model", [PaperTrade, StrategyShadowTrade])
@pytest.mark.parametrize("side,stop,price", [("LONG", 101, 101.5), ("SHORT", 99, 98.5)])
def test_target1_never_loosens_an_existing_tighter_stop(runtime, model, side, stop, price):
    factory, feed = runtime
    key = add_trade(factory, model, side, stop_loss=stop)
    feed.ingest([tick(price, datetime.now(timezone.utc))])
    assert job.run_paper_trade_fast_exit_job()["partial_closes"] == 1
    with factory() as db:
        row = db.get(model, key)
        assert row.stop_loss >= stop if side == "LONG" else row.stop_loss <= stop


def test_gap_loss_is_not_artificially_capped_to_stop_percentage(runtime):
    factory, feed = runtime
    key = add_trade(factory, StrategyShadowTrade)
    feed.ingest([tick(97, datetime.now(timezone.utc))])
    job.run_paper_trade_fast_exit_job()
    with factory() as db:
        row = db.get(StrategyShadowTrade, key)
        assert row.exit_price <= 97
        assert row.pnl_percent < -3


@pytest.mark.parametrize("side,price,reversal", [("LONG", 101, 100.5), ("SHORT", 99, 99.5)])
def test_trailing_stop_tightens_without_retreating_or_spamming(runtime, side, price, reversal):
    factory, feed = runtime
    key = add_trade(factory, PaperTrade, side)
    now = datetime.now(timezone.utc)
    feed.ingest([tick(price, now)])
    assert job.run_paper_trade_fast_exit_job()["stop_moves"] == 1
    with factory() as db:
        stop = db.get(PaperTrade, key).stop_loss
        assert db.query(AppNotification).count() == 0
    feed.ingest([tick(reversal, now + timedelta(milliseconds=50))])
    job.run_paper_trade_fast_exit_job()
    with factory() as db:
        assert db.get(PaperTrade, key).stop_loss == stop


def test_lock_reloads_closed_trade_instead_of_double_closing(runtime):
    factory, _ = runtime
    key = add_trade(factory, PaperTrade)
    with factory() as first:
        stale = first.get(PaperTrade, key)
        with factory() as second:
            second.get(PaperTrade, key).status = "CLOSED"
            second.commit()
        assert lock_open_trade(first, stale) is None


def test_candle_before_live_stop_move_is_not_replayed_with_new_stop():
    now = datetime.utcnow()
    trade = SimpleNamespace(last_exit_evaluated_at=now)
    candle = SimpleNamespace(open_time=now - timedelta(minutes=2), live_mark=False)
    assert _predates_live_protection(trade, candle)
    candle.live_mark = True
    assert not _predates_live_protection(trade, candle)


def test_recovery_checkpoint_cannot_overwrite_newer_fast_protection(runtime):
    factory, _ = runtime
    now = datetime.utcnow()
    key = add_trade(factory, PaperTrade, last_exit_evaluated_at=now)
    with factory() as db:
        trade = db.get(PaperTrade, key)
        advance_exit_checkpoint(db, trade, now - timedelta(minutes=1))
        assert trade.last_exit_evaluated_at == now
