from app.backtesting import filtered_replay_engine


def _feature_resolver(_timestamp):
    return {
        "feature": {
            "trend_score": 35,
            "trend": "BEARISH",
            "momentum_score": 42,
            "volatility_score": 50,
            "liquidity_score": 50,
            "final_score": 40,
            "atr": 1,
        }
    }


def _stack(*, seller_control, bearish_structure):
    orderflow = {
        "signal": "SELL" if seller_control else "BUY",
        "delta": -10 if seller_control else 10,
        "buyer_strength": 40 if seller_control else 60,
        "seller_strength": 60 if seller_control else 40,
        "buy_volume": 40 if seller_control else 60,
        "sell_volume": 60 if seller_control else 40,
        "exhaustion": "NONE",
    }
    smc = {
        "bos": {
            "detected": bearish_structure,
            "direction": "BEARISH" if bearish_structure else "NONE",
        },
        "bias": "SHORT" if bearish_structure else "NEUTRAL",
    }
    return {
        "status": "READY",
        "timeframes": [
            {
                "bias": "WEAK_SHORT",
                "intelligence": {"orderflow": orderflow, "smc": smc},
            },
            {"bias": "WEAK_SHORT"},
            {"bias": "WEAK_SHORT"},
        ],
        "confirmation": {
            "trade_permission": "SHORT_ALLOWED",
            "stack_state": "MIXED_LIGHT",
            "confidence_penalty": 0,
        },
    }


def _decision(monkeypatch, *, regime, seller_control=False, bearish_structure=False):
    monkeypatch.setattr(
        filtered_replay_engine,
        "detect_regime",
        lambda _snapshot: {"regime": regime, "confidence": 60},
    )
    candle = type("Candle", (), {"candle_time": "2026-01-01T00:00:00"})()
    return filtered_replay_engine.build_candle_decision(
        [candle],
        "SHORT",
        60,
        feature_resolver=_feature_resolver,
        stack_context=_stack(
            seller_control=seller_control,
            bearish_structure=bearish_structure,
        ),
        gate_profile="BEAR_RALLY_EXHAUSTION_RESEARCH",
    )


def test_bear_rally_requires_seller_control_and_bearish_structure(monkeypatch):
    decision = _decision(
        monkeypatch,
        regime="BEAR_RALLY",
        seller_control=True,
        bearish_structure=True,
    )

    assert decision["eligible"] is True
    assert decision["research_gate_evidence"]["bear_rally_exhaustion"][
        "confirmed"
    ] is True


def test_bear_rally_without_exhaustion_is_blocked(monkeypatch):
    decision = _decision(monkeypatch, regime="BEAR_RALLY")

    assert decision["eligible"] is False
    assert "BEAR_RALLY_EXHAUSTION_NOT_CONFIRMED" in decision["blocked_reasons"]


def test_non_bear_rally_does_not_require_exhaustion(monkeypatch):
    decision = _decision(monkeypatch, regime="RANGE_DISTRIBUTION")

    assert decision["eligible"] is True
    assert decision["research_gate_evidence"] == {}
