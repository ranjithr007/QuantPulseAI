from app.backtesting.replay_decision_chain import build_replay_decision_chain


GOLDEN_INPUT = {
    "signal": {
        "signal": "LONG",
        "bias": "LONG",
        "confidence": 80,
        "score": 55,
    },
    "feature": {
        "trend": "BULLISH",
        "trend_score": 75,
        "liquidity_score": 65,
        "final_score": 75,
        "atr": 2,
    },
    "regime": {"regime": "TRENDING_BULL", "confidence": 75},
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
GOLDEN_DERIVATIVES = {
    "funding": {"rate": 0.0001},
    "open_interest": {"change_pct": 1.5},
}
GOLDEN_INPUT_FINGERPRINT = (
    "32bcf9a8c6aa12d0bb35de4085201256ab1aa074184aa483b26b681b81eaf176"
)
GOLDEN_DECISION_FINGERPRINT = (
    "86f7e6a8826201341def48aa2f575615484d59727bf4424d6567fe0f35acfbf5"
)


def _decision(intelligence=None):
    return build_replay_decision_chain(
        "DOGEUSDT",
        "1h",
        intelligence or GOLDEN_INPUT,
        GOLDEN_DERIVATIVES,
    )


def test_golden_decision_is_byte_stable_for_identical_frozen_context():
    first = _decision()
    second = _decision()

    assert first["parity"] == second["parity"]
    assert first["parity"]["contract_version"] == "decision_parity_v1"
    assert first["parity"]["input_fingerprint"] == GOLDEN_INPUT_FINGERPRINT
    assert first["parity"]["decision_fingerprint"] == GOLDEN_DECISION_FINGERPRINT


def test_golden_fingerprint_detects_decision_input_drift():
    changed = {
        **GOLDEN_INPUT,
        "signal": {**GOLDEN_INPUT["signal"], "confidence": 39},
    }

    baseline = _decision()
    drifted = _decision(changed)

    assert baseline["parity"]["input_fingerprint"] != drifted["parity"]["input_fingerprint"]
    assert baseline["parity"]["decision_fingerprint"] != drifted["parity"]["decision_fingerprint"]
    assert baseline["executor"]["verdict"] == "WOULD_QUEUE"
    assert drifted["executor"]["verdict"] == "BLOCKED"
