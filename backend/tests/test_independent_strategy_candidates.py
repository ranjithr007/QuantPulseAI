from datetime import datetime, timezone

from app.strategies.candidate_builders import build_liquidation_carry_payload
from app.strategies.candidate_builders import build_orderflow_smc_payload
from app.strategies.candidate_builders import build_regime_trend_payload


def _timeframe(label, now, *, component_scores, stale=()):
    return {
        "timeframe": label,
        "status": "OK",
        "candle_time": now,
        "current_price": 100.0,
        "freshness": {"is_stale": False},
        "inputs": {
            name: {"is_stale": name in stale}
            for name in ("feature", "regime", "orderflow", "smc")
        },
        "component_scores": component_scores,
    }


def _core_payload(now, *, component_scores, stale=()):
    return {
        "symbol": "BTCUSDT",
        "mode": "intraday",
        "timeframes_used": ["1h", "2h", "4h", "1d"],
        "timeframes": [
            _timeframe(label, now, component_scores=component_scores, stale=stale)
            for label in ("1h", "2h", "4h", "1d")
        ],
    }


def _components():
    return {
        "feature": {"score": 20.0, "value": "BULLISH", "reason": "Bull feature"},
        "regime": {"score": 20.0, "value": "TRENDING_BULL", "reason": "Bull regime"},
        "orderflow": {"score": 22.0, "value": "BUYERS_CONTROL", "reason": "Buyers"},
        "smc": {"score": 22.0, "value": "LONG", "reason": "Bull structure"},
    }


def _market_participation(now, *, observed=True, aligned=True):
    return {
        "status": "READY",
        "quality_state": "OK",
        "effective_timestamp": now,
        "data_generation_id": "generation-1",
        "components": {
            "derivatives": 8.0 if aligned else -8.0,
            "liquidation": 8.0,
        },
        "derivatives": {
            "funding_rate": 0.0001,
            "open_interest_change_percent": 2.0,
        },
        "liquidation": {
            "status": "READY" if observed else "UNAVAILABLE",
            "data_quality": "OBSERVED" if observed else "ESTIMATED_OR_MISSING",
            "bias": "HUNT_SHORTS",
        },
        "spot": {
            "timeframes": [
                {
                    "timeframe": label,
                    "status": "READY",
                    "score": 55.0,
                    "direction": "BULLISH",
                    "spot_price": 100.0,
                    "source_timestamp": now,
                }
                for label in ("1h", "2h", "4h", "1d")
            ]
        },
    }


def test_regime_trend_ignores_stale_orderflow_and_smc_when_own_inputs_are_fresh():
    now = datetime.now(timezone.utc)
    payload = build_regime_trend_payload(
        _core_payload(now, component_scores=_components(), stale=("orderflow", "smc"))
    )

    assert payload["trigger"]["status"] == "READY"
    assert payload["trigger"]["side"] == "LONG"
    assert payload["confirmation"]["confidence"] >= 40
    assert set(payload["timeframes"][0]["component_scores"]) == {
        "feature",
        "regime",
    }


def test_orderflow_smc_ignores_stale_feature_and_regime_when_own_inputs_are_fresh():
    now = datetime.now(timezone.utc)
    payload = build_orderflow_smc_payload(
        _core_payload(now, component_scores=_components(), stale=("feature", "regime"))
    )

    assert payload["trigger"]["status"] == "READY"
    assert payload["trigger"]["side"] == "LONG"
    assert set(payload["timeframes"][0]["component_scores"]) == {
        "orderflow",
        "smc",
    }


def test_component_strategy_waits_when_required_engines_disagree():
    now = datetime.now(timezone.utc)
    components = _components()
    components["regime"] = {
        "score": -20.0,
        "value": "TRENDING_BEAR",
        "reason": "Bear regime",
    }
    payload = build_regime_trend_payload(
        _core_payload(now, component_scores=components)
    )

    assert payload["trigger"]["status"] == "WAIT"
    assert "disagree" in payload["trigger"]["reason"].lower()


def test_liquidation_carry_requires_aligned_observed_complete_evidence():
    now = datetime.now(timezone.utc)
    core = _core_payload(now, component_scores=_components())

    ready = build_liquidation_carry_payload(
        core,
        _market_participation(now, observed=True, aligned=True),
    )
    unavailable = build_liquidation_carry_payload(
        core,
        _market_participation(now, observed=False, aligned=True),
    )
    conflict = build_liquidation_carry_payload(
        core,
        _market_participation(now, observed=True, aligned=False),
    )

    assert ready["trigger"]["status"] == "READY"
    assert ready["trigger"]["side"] == "LONG"
    assert ready["trade_plan_validation"]["is_valid"] is True
    assert unavailable["trigger"]["status"] == "WAIT"
    assert "observed liquidation" in unavailable["trigger"]["reason"].lower()
    assert conflict["trigger"]["status"] == "WAIT"
    assert "same direction" in conflict["trigger"]["reason"].lower()
