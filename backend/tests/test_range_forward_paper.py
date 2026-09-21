import pandas as pd
import pytest

from app.paper_trading.range_experiment import initial_state, paper_cycle, SYMBOLS


def inputs(now, price=100., update=1):
    books = {s:{"received_at":now.isoformat(), "latency_seconds":.1,
                "book":{"lastUpdateId":update, "bids":[[str(price-.01),"1000"]],
                        "asks":[[str(price+.01),"1000"]]}} for s in SYMBOLS}
    features = {s:{"available_at":now.floor("h").isoformat(), "signal":True,
                   "stop":97.5, "atr":1., "close":100., "fixed_target":105.,
                   "max_stop_atr":3., "entry_cap_atr":.25, "max_hold_hours":24,
                   "regime_exit_reason":"RANGE_BREAK", "trend_exit":False,
                   "turnover":1e9, "quote_volume":1e7} for s in SYMBOLS}
    metadata = {s:{"status":"TRADING", "isSpotTradingAllowed":True, "filters":[
        {"filterType":"LOT_SIZE","stepSize":"0.001","minQty":"0.001","maxQty":"10000"},
        {"filterType":"PRICE_FILTER","tickSize":"0.01"},
        {"filterType":"MIN_NOTIONAL","minNotional":"5"}]} for s in SYMBOLS}
    return books, features, metadata


def test_one_virtual_entry_per_coin_dedup_and_risk():
    now = pd.Timestamp("2026-09-21T10:00:10Z")
    state = initial_state(now-pd.Timedelta(minutes=1), "hash")
    books, features, metadata = inputs(now)
    state, events = paper_cycle(state, now, books, features, metadata, {})
    assert len(state["positions"]) == 2
    assert sum(p["risk_budget"] for p in state["positions"].values()) <= 20
    assert state["cash"] >= 0
    assert state["live_execution_enabled"] is False
    later = now+pd.Timedelta(seconds=15)
    books, _, _ = inputs(later, update=2)
    repeated, events = paper_cycle(state, later, books, features, metadata, {})
    assert not any(e["kind"]=="PAPER_ENTRY" for e in events)
    assert repeated["daily_entries"] == 2


def test_stop_and_target_net_accounting_and_cooldown():
    now = pd.Timestamp("2026-09-21T10:00:10Z")
    state = initial_state(now-pd.Timedelta(minutes=1), "hash")
    books, features, metadata = inputs(now)
    state, _ = paper_cycle(state, now, books, features, metadata, {})
    later = now+pd.Timedelta(seconds=15)
    books, _, _ = inputs(later, price=97., update=2)
    closed, events = paper_cycle(state, later, books, features, metadata, {})
    exits = [e for e in events if e["kind"]=="PAPER_EXIT"]
    assert len(exits)==2 and all(e["reason"]=="STOP" for e in exits)
    assert closed["positions"] == {}
    assert closed["cash"]-10000 == pytest.approx(sum(e["net_pnl"] for e in exits))
    assert closed["net_pnl"] < 0
    assert set(closed["cooldown"]) == set(SYMBOLS)


def test_no_retrospective_entries_or_stale_book_entries():
    now = pd.Timestamp("2026-09-21T10:00:10Z")
    books, features, metadata = inputs(now)
    state, _ = paper_cycle(initial_state(now,"hash"), now, books, features, metadata, {})
    assert not state["positions"]
    state = initial_state(now-pd.Timedelta(minutes=1),"hash")
    books["BTCUSDT"]["received_at"] = (now-pd.Timedelta(minutes=1)).isoformat()
    state, _ = paper_cycle(state, now, books, features, metadata, {})
    assert not state["positions"]
    assert not state["data_healthy"]


def test_restart_gap_latches_pause_but_protective_exits_continue():
    now = pd.Timestamp("2026-09-21T10:00:10Z")
    state = initial_state(now-pd.Timedelta(minutes=1),"hash")
    books, features, metadata = inputs(now)
    state, _ = paper_cycle(state, now, books, features, metadata, {})
    later = now+pd.Timedelta(minutes=2)
    books, _, _ = inputs(later, price=106., update=2)
    state, events = paper_cycle(state, later, books, features, metadata, {})
    assert state["halt"] == "MONITORING_GAP"
    assert not state["positions"]
    assert all(e["reason"]=="TARGET" for e in events if e["kind"]=="PAPER_EXIT")


def test_pause_prevents_entries_and_completed_bars_reconcile_stop():
    now = pd.Timestamp("2026-09-21T10:00:10Z")
    original = initial_state(now-pd.Timedelta(minutes=1),"hash")
    books, features, metadata = inputs(now)
    paused = {**original,"manual_pause":True}
    paused, _ = paper_cycle(paused, now, books, features, metadata,{})
    assert not paused["positions"]
    state, _ = paper_cycle(original, now, books, features, metadata,{})
    later = pd.Timestamp("2026-09-21T10:30:10Z")
    books, _, _ = inputs(later, update=2)
    bars = {s:[{"time":"2026-09-21T10:15:00Z","end":"2026-09-21T10:30:00Z",
                 "open":100.,"low":96.,"high":101.}] for s in SYMBOLS}
    state, events = paper_cycle(state, later, books, features, metadata,bars)
    assert not state["positions"]
    assert all(e["evidence"]=="CONSERVATIVE_CANDLE_RECONCILIATION" for e in events if e["kind"]=="PAPER_EXIT")
