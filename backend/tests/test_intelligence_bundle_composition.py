from datetime import datetime
from types import SimpleNamespace

from app.api.v1 import signals_api
from app.api.v1 import intelligence_api


def test_multi_timeframe_context_is_reused_across_bundle_builders(monkeypatch):
    diagnostics_calls = []

    def diagnostics(db, symbol, timeframe, stale_after_seconds):
        diagnostics_calls.append(timeframe)
        return {"symbol": symbol, "timeframe": timeframe}

    monkeypatch.setattr(signals_api, "_build_signal_diagnostics", diagnostics)
    monkeypatch.setattr(
        signals_api,
        "combine_timeframe_signals",
        lambda timeframes: {"overall_bias": "WAIT", "trade_permission": "WAIT"},
    )
    
    monkeypatch.setattr(
        signals_api,
        "build_trade_setup_decision",
        lambda confirmation, timeframes: {"status": "WAIT", "side": None},
    )
    monkeypatch.setattr(
        signals_api,
        "build_entry_trigger_decision",
        lambda confirmation, timeframes: {
            "status": "WAIT",
            "side": None,
            "reason": "No setup",
            "conditions": [],
        },
    )
    monkeypatch.setattr(
        signals_api,
        "build_scenario_plan",
        lambda confirmation, timeframes, **kwargs: {"status": "WAIT"},
    )

    context = signals_api.build_multi_timeframe_context(
        object(),
        "BTCUSDT",
        mode="intraday",
        stale_after_seconds=900,
    )
    signals_api.build_multi_timeframe_signal_payload(
        object(), "BTCUSDT", mode="intraday", context=context
    )
    signals_api.build_trade_setup_payload(
        object(), "BTCUSDT", mode="intraday", context=context
    )
    signals_api.build_entry_trigger_payload(
        object(), "BTCUSDT", mode="intraday", context=context
    )

    assert diagnostics_calls == ["1h", "2h", "4h", "1d"]


def test_intelligence_bundle_uses_session_aware_payload_builders():
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "api"
        / "v1"
        / "intelligence_api.py"
    ).read_text(encoding="utf-8")

    assert "build_market_candles_payload(db" in source
    assert "build_orderflow_payload(db" in source
    assert "build_smc_payload(db" in source
    assert "build_risk_payload(db" in source
    assert "build_ai_scores_payload(db" in source
    assert source.count("context=multi_timeframe_context") == 3


def test_intelligence_as_of_snapshot_endpoint_uses_point_in_time_tables(monkeypatch):
    calls = {}

    def feature_snapshot(db, symbol, timeframe, as_of):
        calls["feature"] = (symbol, timeframe, as_of)
        return SimpleNamespace(
            id=11,
            symbol=symbol,
            timeframe=timeframe,
            source_timestamp=as_of,
            effective_timestamp=as_of,
            feature_version="feature_factory_v1",
            quality_state="OK",
            snapshot_json='{"kind":"feature"}',
        )

    def decision_snapshot(db, symbol, timeframe, as_of):
        calls["decision"] = (symbol, timeframe, as_of)
        return SimpleNamespace(
            id=22,
            symbol=symbol,
            timeframe=timeframe,
            source_timestamp=as_of,
            effective_timestamp=as_of,
            feature_version="feature_factory_v1",
            decision_version="decision_contract_v1",
            quality_state="OK",
            snapshot_json='{"kind":"decision"}',
        )

    def point_in_time_bundle(db, symbol, timeframe, as_of):
        feature = feature_snapshot(db, symbol, timeframe, as_of)
        decision = decision_snapshot(db, symbol, timeframe, as_of)
        return {
            "feature_snapshot": feature,
            "decision_snapshot": decision,
            "serialized": {"thesis_snapshot": None},
            "feature_leakage_diagnostics": {
                "status": "PASS",
                "feature": {"within_as_of": True},
                "decision": {"version_matches": True},
            },
            "thesis_leakage_diagnostics": {"status": "NO_DATA"},
        }

    monkeypatch.setattr(
        intelligence_api, "build_point_in_time_bundle", point_in_time_bundle
    )

    class FakeDb:
        def rollback(self):
            raise AssertionError("rollback should not be called")

        def close(self):
            return None

    monkeypatch.setattr(intelligence_api, "SessionLocal", lambda: FakeDb())

    payload = intelligence_api.get_intelligence_snapshot_as_of(
        "BTCUSDT",
        timeframe="15m",
        as_of=datetime(2026, 6, 24, 3, 0, 0),
    )

    assert calls["feature"][0] == "BTCUSDT"
    assert calls["decision"][1] == "15m"
    assert payload["source"] == "point_in_time_snapshot"
    assert payload["feature_snapshot"]["snapshot"]["kind"] == "feature"
    assert payload["decision_snapshot"]["snapshot"]["kind"] == "decision"
    assert payload["leakage_diagnostics"]["status"] == "PASS"
    assert payload["leakage_diagnostics"]["feature"]["within_as_of"] is True
    assert payload["leakage_diagnostics"]["decision"]["version_matches"] is True


def test_trade_setup_payload_persists_ready_decision_snapshot(monkeypatch):
    calls = {}
    db = object()
    context = {
        "stack": ["5m", "15m", "1h"],
        "timeframes": [{"timeframe": "5m"}],
        "confirmation": {
            "overall_bias": "BULLISH_ALIGNMENT",
            "trade_permission": "LONG_ALLOWED",
            "confidence": 81,
        },
    }
    candle = SimpleNamespace(
        candle_time=datetime(2026, 6, 24, 3, 0, 0), close_price=100
    )
    feature = SimpleNamespace(ATR=1.5)
    snapshot_record = SimpleNamespace(
        id=99,
        decision_version="decision_contract_v1",
        effective_timestamp=candle.candle_time,
    )

    def persist_snapshot(db_arg, snapshot):
        calls["snapshot"] = snapshot
        return snapshot_record

    monkeypatch.setattr(signals_api, "_latest_candle", lambda *args, **kwargs: candle)
    monkeypatch.setattr(
        signals_api, "get_ai_inputs", lambda *args, **kwargs: {"feature": feature}
    )
    monkeypatch.setattr(
        signals_api,
        "build_trade_setup_decision",
        lambda confirmation, timeframes: {
            "status": "READY",
            "side": "LONG",
            "reason": "ready",
        },
    )
    monkeypatch.setattr(
        signals_api,
        "build_scenario_plan",
        lambda confirmation, timeframes, **kwargs: {"status": "READY"},
    )
    monkeypatch.setattr(
        signals_api,
        "build_trade_plan",
        lambda side, current_price, atr, **kwargs: {
            "entry": current_price,
            "target1": current_price + 2,
            "target2": current_price + 3,
        },
    )
    monkeypatch.setattr(
        signals_api,
        "validate_trade_plan_direction",
        lambda side, entry, target1: {"is_valid": True, "errors": []},
    )
    monkeypatch.setattr(signals_api, "persist_decision_snapshot", persist_snapshot)

    payload = signals_api.build_trade_setup_payload(
        db, "BTCUSDT", mode="intraday", context=context
    )

    assert calls["snapshot"]["decision"] == "READY"
    assert calls["snapshot"]["trade_plan"]["entry"] == 100
    assert payload["decision_snapshot"]["id"] == 99
    assert payload["trade_plan"]["entry"] == 100


def test_intelligence_bundle_returns_partial_payload_when_one_section_fails(
    monkeypatch,
):
    calls = []

    class FakeDb:
        def rollback(self):
            calls.append("rollback")

        def close(self):
            calls.append("close")

    monkeypatch.setattr(intelligence_api, "SessionLocal", lambda: FakeDb())
    monkeypatch.setattr(
        intelligence_api,
        "build_signal_payload",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("boom")),
    )
    monkeypatch.setattr(
        intelligence_api,
        "build_signal_diagnostics_payload",
        lambda *args, **kwargs: {"source": "diagnostics", "status": "OK"},
    )
    monkeypatch.setattr(
        intelligence_api,
        "build_market_candles_payload",
        lambda *args, **kwargs: {"source": "candles", "status": "OK"},
    )
    monkeypatch.setattr(
        intelligence_api,
        "build_orderflow_payload",
        lambda *args, **kwargs: {"source": "orderflow", "status": "OK"},
    )
    monkeypatch.setattr(
        intelligence_api,
        "build_smc_payload",
        lambda *args, **kwargs: {"source": "smc", "status": "OK"},
    )
    monkeypatch.setattr(
        intelligence_api,
        "build_risk_payload",
        lambda *args, **kwargs: {"source": "risk", "status": "OK"},
    )
    monkeypatch.setattr(
        intelligence_api,
        "build_ai_scores_payload",
        lambda *args, **kwargs: {"source": "aiScores", "status": "OK"},
    )
    monkeypatch.setattr(
        intelligence_api,
        "build_derivatives_payload",
        lambda *args, **kwargs: {
            "source": "derivatives",
            "status": "OK",
        },
    )
    monkeypatch.setattr(
        intelligence_api,
        "build_multi_timeframe_context",
        lambda *args, **kwargs: {
            "stack": ["5m", "15m", "1h"],
            "timeframes": [],
            "confirmation": {},
        },
    )
    monkeypatch.setattr(
        intelligence_api,
        "build_multi_timeframe_signal_payload",
        lambda *args, **kwargs: {"source": "multiTimeframe", "status": "OK"},
    )
    monkeypatch.setattr(
        intelligence_api,
        "build_trade_setup_payload",
        lambda *args, **kwargs: {"source": "tradeSetup", "status": "OK"},
    )
    monkeypatch.setattr(
        intelligence_api,
        "build_entry_trigger_payload",
        lambda *args, **kwargs: {"source": "entryTrigger", "status": "OK"},
    )

    payload = intelligence_api.get_intelligence_bundle(
        "DOGEUSDT",
        timeframe="1d",
        mode="intraday",
        stale_after_seconds=900,
    )

    assert payload["signal"]["status"] == "FAILED"
    assert payload["signal"]["error"] == "boom"
    assert payload["diagnostics"]["status"] == "OK"
    assert payload["multiTimeframe"]["status"] == "OK"
    assert payload["bundleStatus"] == "PARTIAL"
    assert payload["failures"] == [{"section": "signal", "error": "boom"}]
    assert calls == ["rollback", "close"]


def test_entry_trigger_payload_persists_ready_decision_snapshot(monkeypatch):
    calls = {}
    db = object()
    context = {
        "stack": ["5m", "15m", "1h"],
        "timeframes": [{"timeframe": "5m"}],
        "confirmation": {
            "overall_bias": "BULLISH_ALIGNMENT",
            "trade_permission": "LONG_ALLOWED",
            "confidence": 82,
        },
    }
    candle = SimpleNamespace(
        candle_time=datetime(2026, 6, 24, 3, 0, 0), close_price=100
    )
    feature = SimpleNamespace(ATR=1.5)
    snapshot_record = SimpleNamespace(
        id=100,
        decision_version="decision_contract_v1",
        effective_timestamp=candle.candle_time,
    )

    def persist_snapshot(db_arg, snapshot):
        calls["snapshot"] = snapshot
        return snapshot_record

    monkeypatch.setattr(signals_api, "_latest_candle", lambda *args, **kwargs: candle)
    monkeypatch.setattr(
        signals_api, "get_ai_inputs", lambda *args, **kwargs: {"feature": feature}
    )
    monkeypatch.setattr(
        signals_api,
        "build_entry_trigger_decision",
        lambda confirmation, timeframes: {
            "status": "READY",
            "side": "LONG",
            "reason": "ready",
            "conditions": [],
        },
    )
    monkeypatch.setattr(
        signals_api,
        "build_trade_plan",
        lambda side, current_price, atr, **kwargs: {
            "entry": current_price,
            "target1": current_price + 2,
            "target2": current_price + 3,
        },
    )
    monkeypatch.setattr(
        signals_api,
        "validate_trade_plan_direction",
        lambda side, entry, target1: {"is_valid": True, "errors": []},
    )
    monkeypatch.setattr(signals_api, "persist_decision_snapshot", persist_snapshot)

    payload = signals_api.build_entry_trigger_payload(
        db, "BTCUSDT", mode="intraday", context=context
    )

    assert calls["snapshot"]["decision"] == "READY"
    assert calls["snapshot"]["trade_plan"]["entry"] == 100
    assert payload["decision_snapshot"]["id"] == 100
    assert payload["trigger"]["status"] == "READY"


def test_entry_trigger_payload_builds_plan_from_selected_governed_timeframe(monkeypatch):
    requested_timeframes = []
    candle = SimpleNamespace(
        candle_time=datetime(2026, 8, 13, 4, 0, 0), close_price=100
    )
    context = {
        "prediction_stack": ["1h", "2h", "4h", "1d"],
        "prediction_timeframes": [
            {"timeframe": "1h", "confidence": 45},
            {"timeframe": "2h", "confidence": 50},
            {"timeframe": "4h", "confidence": 70},
            {"timeframe": "1d", "confidence": 65},
        ],
        "entry_stack": [],
        "confirmation": {
            "overall_bias": "MIXED",
            "trade_permission": "WAIT",
        },
    }

    def latest_candle(db, symbol, timeframe):
        requested_timeframes.append(("candle", timeframe))
        return candle

    def ai_inputs(db, symbol, timeframe):
        requested_timeframes.append(("inputs", timeframe))
        return {"feature": SimpleNamespace(ATR=1.0)}

    monkeypatch.setattr(signals_api, "_latest_candle", latest_candle)
    monkeypatch.setattr(signals_api, "get_ai_inputs", ai_inputs)
    monkeypatch.setattr(
        signals_api,
        "build_entry_trigger_decision",
        lambda confirmation, timeframes: {
            "status": "READY",
            "side": "LONG",
            "reason": "4h is strongest",
            "conditions": [],
            "entry_timeframe": "4h",
        },
    )
    monkeypatch.setattr(
        signals_api,
        "build_scenario_plan",
        lambda *args, **kwargs: {"status": "READY"},
    )
    monkeypatch.setattr(
        signals_api,
        "build_trade_plan",
        lambda side, current_price, atr, **kwargs: {
            "entry": current_price,
            "stop_loss": 99,
            "target1": 102,
            "target2": 103,
        },
    )
    monkeypatch.setattr(
        signals_api,
        "validate_trade_plan_direction",
        lambda *args: {"is_valid": True, "errors": []},
    )
    monkeypatch.setattr(
        signals_api,
        "persist_decision_snapshot",
        lambda db, snapshot: SimpleNamespace(
            id=101,
            decision_version="decision_contract_v1",
            effective_timestamp=candle.candle_time,
        ),
    )

    payload = signals_api.build_entry_trigger_payload(
        object(), "BTCUSDT", context=context
    )

    assert requested_timeframes == [("candle", "4h"), ("inputs", "4h")]
    assert payload["trigger"]["entry_timeframe"] == "4h"
    assert payload["trade_plan"]["entry"] == 100
