from app.backtesting import filtered_replay_engine


def _feature_resolver(
    *,
    trend_score=35,
    momentum_score=42,
    final_score=40,
):
    def resolve(_timestamp):
        return {
            "feature": {
                "trend_score": trend_score,
                "trend": "BEARISH",
                "momentum_score": momentum_score,
                "volatility_score": 50,
                "liquidity_score": 50,
                "final_score": final_score,
                "atr": 1,
            }
        }

    return resolve


def _decision(monkeypatch, *, regime="RANGE_NEUTRAL", confidence=60, **features):
    monkeypatch.setattr(
        filtered_replay_engine,
        "detect_regime",
        lambda _snapshot: {"regime": regime, "confidence": confidence},
    )
    candle = type("Candle", (), {"candle_time": "2026-01-01T00:00:00"})()
    return filtered_replay_engine.build_candle_decision(
        [candle],
        "SHORT",
        60,
        feature_resolver=_feature_resolver(**features),
        gate_profile="SHORT_EDGE_RESEARCH",
    )


def test_short_edge_profile_accepts_bounded_neutral_regime_setup(monkeypatch):
    decision = _decision(monkeypatch)

    assert decision["eligible"] is True
    assert decision["signal"] == "SHORT"


def test_short_edge_profile_blocks_exhausted_short(monkeypatch):
    decision = _decision(
        monkeypatch,
        trend_score=20,
        final_score=30,
    )

    assert decision["eligible"] is False
    assert "TREND_TOO_EXTENDED_BEARISH" in decision["blocked_reasons"]
    assert "FEATURE_SIGNAL_TOO_EXTENDED_SHORT" in decision["blocked_reasons"]


def test_short_edge_profile_blocks_bear_rally_and_high_confidence(monkeypatch):
    decision = _decision(
        monkeypatch,
        regime="BEAR_RALLY",
        confidence=80,
    )

    assert decision["eligible"] is False
    assert "REGIME_CONFLICT_OR_REVERSAL" in decision["blocked_reasons"]
    assert "CONFIDENCE_ABOVE_PROFILE_WINDOW" in decision["blocked_reasons"]
