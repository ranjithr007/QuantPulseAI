from app.backtesting.replay_decision_chain import build_replay_decision_chain


def _long_intelligence(confidence=80):
    return {
        "signal": {
            "signal": "LONG",
            "bias": "LONG",
            "confidence": confidence,
            "score": 55,
        },
        "feature": {
            "trend": "BULLISH",
            "trend_score": 75,
            "liquidity_score": 65,
            "final_score": 75,
            "atr": 2,
        },
        "regime": {
            "regime": "TRENDING_BULL",
            "confidence": 75,
        },
        "orderflow": {
            "signal": "BUYERS_CONTROL",
            "confidence": 70,
            "buyer_strength": 65,
            "seller_strength": 35,
            "delta": 100,
            "cvd": 200,
            "absorption": "NONE",
        },
        "smc": {
            "bias": "LONG",
            "confidence": 70,
            "bos": {"direction": "BULLISH"},
            "sweep": {"type": "NONE"},
        },
        "current_price": 100,
        "previous_price": 99,
        "price_change_pct": 1.0101,
    }


def _derivatives():
    return {
        "funding": {"rate": 0.0001},
        "open_interest": {"change_pct": 1.5},
    }


def test_replay_decision_chain_would_queue_without_creating_trade():
    result = build_replay_decision_chain(
        "DOGEUSDT",
        "1h",
        _long_intelligence(),
        _derivatives(),
    )

    assert result["contradiction"]["trade_allowed"] is True
    assert result["risk"]["decision"] == "APPROVE"
    assert result["executor"] == {
        "verdict": "WOULD_QUEUE",
        "side_effect": "NONE",
        "paper_trade_created": False,
    }
    assert result["leakage_status"] == "PASS"


def test_replay_decision_chain_blocks_low_confidence_at_risk_gate():
    result = build_replay_decision_chain(
        "DOGEUSDT",
        "1h",
        _long_intelligence(confidence=55),
        _derivatives(),
    )

    assert result["risk"]["decision"] == "REJECT"
    assert result["risk"]["reason"] == "Confidence below risk threshold"
    assert result["executor"]["verdict"] == "BLOCKED"
    assert result["executor"]["paper_trade_created"] is False
