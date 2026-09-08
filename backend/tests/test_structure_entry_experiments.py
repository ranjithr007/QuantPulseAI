import copy
from datetime import datetime, timedelta, timezone

import pytest

from app.api.v1 import signals_api
from app.strategies.candidate_builders import build_regime_trend_payload
from app.strategies.entry_quality import revalidate_entry_candidate
from app.strategies.registry import strategy_definition
from app.strategies.structure_entry import (
    STRUCTURE_PROFILE, build_structure_entry_payload, rebuild_core_entry_payload,
)
from app.trading.trade_plan_engine import build_trade_plan
from test_phase1_trade_setup import governed_tf


def inputs(side="LONG"):
    sign = 1 if side == "LONG" else -1
    now = datetime.now(timezone.utc)
    closed = now - timedelta(minutes=5)
    frames = []
    spots = []
    for tf, score in zip(("1h", "2h", "4h", "1d"), (55, 65, 45, 42)):
        frame = governed_tf(tf, sign * score)
        frame.update(status="OK", candle_time=closed, current_price=100,
                     trade_plan=build_trade_plan(side, 100, confidence=score, symbol="BTCUSDT", timeframe=tf))
        frame["component_scores"].update(feature={"value": side, "score": sign * score / 4},
                                         regime={"value": "TRENDING_BULL" if sign == 1 else "TRENDING_BEAR", "score": sign * score / 4})
        frames.append(frame)
        confirmed = {"confirmed": True, "setup_type": "BREAKOUT_RETEST", "level": 100 - sign * .5,
                     "invalidation_level": 100 - sign, "confirmed_at": closed.isoformat()}
        structure = {"profile": STRUCTURE_PROFILE, "symbol": "BTCUSDT", "timeframe": tf, "status": "READY",
                     "closed_at": closed.isoformat(), "close": 100, "atr": 2,
                     "structure": "BULLISH" if sign == 1 else "BEARISH",
                     "long": confirmed if sign == 1 else {"confirmed": False},
                     "short": confirmed if sign == -1 else {"confirmed": False}}
        spots.append({"symbol": "BTCUSDT", "timeframe": tf, "status": "READY", "spot_price": 100,
                      "score": score * sign, "direction": "BULLISH" if sign == 1 else "BEARISH",
                      "atr": 2, "ema20": 100 - sign * .5, "spot_cvd_percent": sign * 10,
                      "source_timestamp": closed.isoformat(), "price_structure": structure,
                      "support": {"lower": 98.5}, "resistance": {"upper": 101.5}})
    core = {"symbol": "BTCUSDT", "mode": "intraday", "timeframes": frames,
            "confirmation": {"trade_permission": "WAIT", "confidence": 65, "entry_timeframes": []},
            "trigger": {"status": "READY", "side": side, "entry_timeframe": "2h"},
            "trade_plan": copy.deepcopy(frames[1]["trade_plan"]), "trade_plan_validation": {"is_valid": True, "errors": []}}
    raw = {"symbol": "BTCUSDT", "status": "READY", "quality_state": "OK", "effective_timestamp": now,
           "direction": "BULLISH" if sign == 1 else "BEARISH", "confidence": 65, "score": 65 * sign,
           "spot": {"timeframes": spots}}
    return core, raw, now


def build(family, core, raw, now):
    definition = strategy_definition(family + "_ENTRY")
    if family == "CORE_SIGNAL":
        base = core
        rebuild = lambda gate: rebuild_core_entry_payload(core, gate)
    elif family == "REGIME_TREND":
        base = build_regime_trend_payload(core)
        rebuild = lambda gate: build_regime_trend_payload(core, structure_gate=gate)
    else:
        base = signals_api._build_market_move_strategy_payload(core, raw)
        rebuild = lambda gate: signals_api._build_market_move_strategy_payload(core, raw, structure_gate=gate)
    return base, build_structure_entry_payload(base, raw, definition, rebuild=rebuild, now=now)


@pytest.mark.parametrize("family", ["CORE_SIGNAL", "REGIME_TREND", "MARKET_MOVE"])
@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_entry_only_keeps_score_and_baseline_exit_geometry(family, side):
    core, raw, now = inputs(side)
    original = copy.deepcopy((core, raw))
    base, result = build(family, core, raw, now)
    assert (core, raw) == original
    assert result["trigger"]["status"] == "READY"
    assert result["trigger"]["side"] == side
    for key in ("entry", "stop_loss", "target1", "target2", "exit_policy", "target1_fraction", "max_hold_hours"):
        assert result["trade_plan"][key] == base["trade_plan"][key]
    assert result["trailing_activation_r"] == 0
    assert result["execution_evidence"]["entry_quality_profile"] == STRUCTURE_PROFILE
    assert [t["score"] for t in result["timeframes"]] == [t["score"] for t in base["timeframes"]]


@pytest.mark.parametrize("family", ["CORE_SIGNAL", "REGIME_TREND", "MARKET_MOVE"])
@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_filters_all_timeframes_before_selecting_winner(family, side):
    core, raw, now = inputs(side)
    raw["spot"]["timeframes"][1]["price_structure"][side.lower()] = {"confirmed": False, "reason": "Compression: no confirmed break"}
    _, result = build(family, core, raw, now)
    assert result["trigger"]["status"] == "READY"
    assert result["trigger"]["entry_timeframe"] == "1h"
    assert result["entry_quality"]["timeframe"] == "1h"


@pytest.mark.parametrize("family", ["CORE_SIGNAL", "REGIME_TREND", "MARKET_MOVE"])
def test_high_score_without_price_confirmation_waits(family):
    core, raw, now = inputs()
    for spot in raw["spot"]["timeframes"]:
        spot["price_structure"]["long"] = {"confirmed": False, "reason": "Higher lows alone are not a confirmed trend entry"}
    _, result = build(family, core, raw, now)
    assert result["trigger"]["status"] == "WAIT"
    assert "Higher lows" in result["trigger"]["reason"]


def candidate(side="LONG"):
    core, raw, now = inputs(side)
    _, result = build("CORE_SIGNAL", core, raw, now)
    result["side"] = side
    result["trade_plan"].update(strategy_id="CORE_SIGNAL_ENTRY", strategy_version="core_signal_entry_v1", entry_timeframe="2h")
    return result, now


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_actual_mark_and_fill_revalidation_preserves_exit_model(side):
    result, now = candidate(side)
    evidence, reason = revalidate_entry_candidate(result, {"mark_price": 100, "observed_at": now}, now=now)
    assert reason is None
    assert evidence["entry_quality_passed"]
    assert evidence["setup_type"] == "BREAKOUT_RETEST"
    assert "execution_atr" not in evidence and "execution_structure_level" not in evidence
    _, reason = revalidate_entry_candidate(result, {"mark_price": 101.1 if side == "LONG" else 98.9, "observed_at": now}, now=now)
    assert "0.5 ATR" in reason


@pytest.mark.parametrize("change,fragment", [
    (lambda q,n: q.update(effective_timestamp=n-timedelta(minutes=16)), "fresh scan"),
    (lambda q,n: q.update(atr=float("nan")), "finite"),
    (lambda q,n: q.update(atr=True), "finite"),
    (lambda q,n: q.update(spot_cvd_percent=-1), "CVD"),
    (lambda q,n: q["price_structure"].update(timeframe="1d"), "timeframe"),
    (lambda q,n: q["price_structure"].update(symbol="ETHUSDT"), "coin"),
    (lambda q,n: q["price_structure"].update(closed_at=(n+timedelta(hours=1)).isoformat()), "same closed candle"),
    (lambda q,n: q["price_structure"]["long"].update(invalidation_level=101), "levels"),
    (lambda q,n: q.update(source_timestamp=n-timedelta(hours=1)), "same closed candle"),
])
def test_frozen_entry_evidence_fails_closed(change, fragment):
    result, now = candidate()
    change(result["entry_quality"], now)
    _, reason = revalidate_entry_candidate(result, {"mark_price": 100, "observed_at": now}, now=now)
    assert fragment in reason


def test_old_closed_candle_cannot_be_rescued_by_fresh_scan():
    result, now = candidate()
    old = (now-timedelta(hours=3)).isoformat()
    result["entry_quality"].update(source_timestamp=old)
    result["entry_quality"]["price_structure"].update(closed_at=old)
    result["entry_quality"]["price_structure"]["long"]["confirmed_at"] = old
    _, reason = revalidate_entry_candidate(result, {"mark_price": 100, "observed_at": now}, now=now)
    assert "stale" in reason


@pytest.mark.parametrize("family", ["CORE_SIGNAL", "REGIME_TREND", "MARKET_MOVE"])
def test_scan_clock_is_independent_of_selected_closed_candle(family):
    core, raw, now = inputs()
    old_close = (now - timedelta(minutes=45)).isoformat()
    raw.update(effective_timestamp=old_close, collected_at=now.isoformat())
    for spot in raw["spot"]["timeframes"]:
        spot["source_timestamp"] = old_close
        spot["price_structure"]["closed_at"] = old_close
        spot["price_structure"]["long"]["confirmed_at"] = old_close
    _, result = build(family, core, raw, now)
    assert result["trigger"]["status"] == "READY"
    assert result["entry_quality"]["effective_timestamp"] == now.isoformat()
    assert result["entry_quality"]["source_timestamp"] == old_close
    raw["collected_at"] = (now - timedelta(minutes=16)).isoformat()
    _, stale = build(family, core, raw, now)
    assert stale["trigger"]["status"] == "WAIT"
    assert "fresh scan" in stale["trigger"]["reason"]


@pytest.mark.parametrize("strategy,version", [("CORE_SIGNAL_ENTRY","core_signal_entry_v1"),
                                             ("REGIME_TREND_ENTRY","regime_trend_entry_v2"),
                                             ("MARKET_MOVE_ENTRY","market_move_entry_v2"),
                                             ("MARKET_MOVE_ENTRY",None)])
def test_missing_metadata_cannot_bypass_current_entry_experiment(strategy, version):
    _, reason = revalidate_entry_candidate({"trade_plan": {"strategy_id": strategy,"strategy_version": version}},
                                           {"mark_price":100,"observed_at":datetime.now(timezone.utc)})
    assert "missing" in reason


def test_old_profile_cannot_bypass_an_unversioned_market_move_entry():
    _, reason = revalidate_entry_candidate({"trade_plan": {"strategy_id": "MARKET_MOVE_ENTRY"},
                                           "entry_quality": {"profile": "MARKET_MOVE_RETEST_V1"}},
                                          {"mark_price": 100, "observed_at": datetime.now(timezone.utc)})
    assert "missing" in reason


def test_ineligible_baseline_is_not_rescued():
    core, raw, now = inputs()
    core["trigger"].update(status="WAIT", reason="Original risk-independent entry gate failed")
    _, result = build("CORE_SIGNAL", core, raw, now)
    assert result["trigger"]["status"] == "WAIT"
    assert result["trigger"]["reason"] == core["trigger"]["reason"]


def test_persist_pipeline_contains_six_separate_frozen_experiments(monkeypatch):
    core, raw, now = inputs()
    def persisted(*args, **kwargs):
        return {"persisted": True, "decision": "ELIGIBLE", "id": 1}
    for name in ("_persist_derived_strategy_snapshot", "_persist_core_signal_strategy_snapshot",
                 "_persist_market_move_strategy_snapshot", "_persist_core_fusion_strategy_snapshot"):
        monkeypatch.setattr(signals_api, name, persisted)
    monkeypatch.setattr(signals_api, "active_candidate_definitions", lambda db: [])
    records = signals_api._persist_strategy_candidates(None, core, raw)
    experiments = {r["definition"]["id"]: r for r in records if r["definition"].get("immutable_experiment")}
    assert set(experiments) == {f+suffix for f in ("CORE_SIGNAL", "REGIME_TREND", "MARKET_MOVE") for suffix in ("_ENTRY","_EXIT")}
    for key, record in experiments.items():
        assert record["definition"]["official_execution_enabled"] is False
        assert record["payload"]["trailing_activation_r"] == (1 if key.endswith("_EXIT") else 0)
