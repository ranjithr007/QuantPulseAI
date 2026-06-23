from app.api.v1 import signals_api


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

    assert diagnostics_calls == ["5m", "15m", "1h"]


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
