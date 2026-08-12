from app.backtesting.filtered_replay_engine import build_candle_decision
from app.regimes.rules import detect_regime_momentum_boundary_research


def _feature_resolver(_timestamp):
    return {
        "feature": {
            "trend_score": 25,
            "trend": "BEARISH",
            "momentum_score": 40,
            "volatility_score": 50,
            "liquidity_score": 50,
            "final_score": 35,
            "atr": 1,
        }
    }


def test_research_detector_can_be_injected_without_changing_strict_gate_profile():
    candle = type("Candle", (), {"candle_time": "2026-01-01T00:00:00"})()

    production = build_candle_decision(
        [candle],
        "SHORT",
        0,
        feature_resolver=_feature_resolver,
        gate_profile="STRICT",
    )
    research = build_candle_decision(
        [candle],
        "SHORT",
        0,
        feature_resolver=_feature_resolver,
        gate_profile="STRICT",
        regime_detector=detect_regime_momentum_boundary_research,
    )

    assert production["eligible"] is False
    assert production["regime"] != "TRENDING_BEAR"
    assert research["eligible"] is True
    assert research["regime"] == "TRENDING_BEAR"
    assert research["regime_detector"] == "detect_regime_momentum_boundary_research"


def test_replay_gate_prefers_candidate_timeframes_stateful_regime():
    candle = type("Candle", (), {"candle_time": "2026-01-01T00:00:00"})()
    timeframes = [
        {"timeframe": timeframe, "bias": "NEUTRAL", "intelligence": {}}
        for timeframe in ("1h", "2h", "4h", "1d")
    ]
    timeframes[2]["intelligence"] = {
        "regime": {"regime": "TRENDING_BEAR", "confidence": 80}
    }
    stack = {
        "status": "READY",
        "decision_chain_timeframe": "4h",
        "timeframes": timeframes,
        "confirmation": {},
    }

    decision = build_candle_decision(
        [candle],
        "SHORT",
        0,
        feature_resolver=_feature_resolver,
        stack_context=stack,
        gate_profile="STRICT",
    )

    assert decision["eligible"] is True
    assert decision["regime"] == "TRENDING_BEAR"
    assert decision["regime_source"] == "POINT_IN_TIME_STATEFUL_STACK"
