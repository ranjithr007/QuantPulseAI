from datetime import datetime, timezone
from types import SimpleNamespace

from app.api.v1.signals_api import _observed_atr
from app.strategies.candidate_builders import build_liquidation_carry_payload
from app.strategies.candidate_builders import build_orderflow_smc_payload
from app.strategies.candidate_builders import build_range_reversion_payload
from app.strategies.candidate_builders import build_regime_trend_payload
from app.strategies.candidate_builders import build_trend_pullback_payload


def test_observed_atr_never_substitutes_the_legacy_one_percent_fallback():
    assert _observed_atr(None) is None
    assert _observed_atr(SimpleNamespace(ATR=None)) is None
    assert _observed_atr(SimpleNamespace(ATR=0)) is None
    assert _observed_atr(SimpleNamespace(ATR=1.25)) == 1.25


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


def _location_market_participation(now, *, rejected=True):
    payload = _market_participation(now)
    payload["spot"]["timeframes"] = [
        {
            **item,
            "spot_price": 100.0,
            "ema20": 99.5,
            "spot_cvd_percent": 2.0,
            "support": {
                "lower": 98.5,
                "upper": 99.5,
                "tests": 3,
                "distance_percent": -1.0,
                "latest_rejected": rejected,
            },
            "resistance": {
                "lower": 102.0,
                "upper": 103.0,
                "tests": 3,
                "distance_percent": 2.5,
                "latest_rejected": False,
            },
        }
        for item in payload["spot"]["timeframes"]
    ]
    return payload


def _location_core(now, regime, *, regime_score=20.0):
    core = _core_payload(now, component_scores=_components())
    for item in core["timeframes"]:
        item["atr"] = 1.5
        item["component_scores"] = {
            **item["component_scores"],
            "regime": {
                "score": regime_score,
                "value": regime,
                "reason": "Routed regime",
            },
        }
    return core


def _bearish_location_market_participation(now, *, rejected=True):
    payload = _location_market_participation(now, rejected=rejected)
    payload["spot"]["timeframes"] = [
        {
            **item,
            "direction": "BEARISH",
            "score": -55.0,
            "spot_price": 100.0,
            "ema20": 100.5,
            "spot_cvd_percent": -2.0,
            "resistance": {
                "lower": 100.5,
                "upper": 101.0,
                "tests": 3,
                "distance_percent": 1.0,
                "latest_rejected": rejected,
            },
        }
        for item in payload["spot"]["timeframes"]
    ]
    return payload


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


def test_trend_pullback_requires_pullback_regime_location_and_fresh_atr():
    now = datetime.now(timezone.utc)
    ready = build_trend_pullback_payload(
        _location_core(now, "BULL_PULLBACK"),
        _location_market_participation(now),
    )
    extended = build_trend_pullback_payload(
        _location_core(now, "TRENDING_BULL"),
        _location_market_participation(now),
    )

    assert ready["trigger"]["status"] == "READY"
    assert ready["trigger"]["side"] == "LONG"
    assert ready["trade_plan"]["exit_policy"] == "PAPER_ATR_STRUCTURE_V1"
    assert ready["trade_plan"]["stop_loss"] <= 98.5
    assert ready["trade_plan"]["target2_net_risk_reward"] >= 2.3
    assert extended["trigger"]["status"] == "WAIT"
    assert "wait for a pullback" in extended["trigger"]["reason"].lower()


def test_bear_rally_short_is_not_cancelled_by_countertrend_feature_score():
    now = datetime.now(timezone.utc)
    payload = build_trend_pullback_payload(
        _location_core(now, "BEAR_RALLY", regime_score=-20.0),
        _bearish_location_market_participation(now),
    )

    assert payload["trigger"]["status"] == "READY"
    assert payload["trigger"]["side"] == "SHORT"
    assert payload["confirmation"]["confidence"] == 80.0
    assert payload["trade_plan_validation"]["is_valid"] is True


def test_range_reversion_fails_closed_without_confirmed_boundary_rejection():
    now = datetime.now(timezone.utc)
    ready = build_range_reversion_payload(
        _location_core(now, "RANGE_ACCUMULATION"),
        _location_market_participation(now, rejected=True),
    )
    middle = build_range_reversion_payload(
        _location_core(now, "RANGE_ACCUMULATION"),
        _location_market_participation(now, rejected=False),
    )

    assert ready["trigger"]["status"] == "READY"
    assert ready["trigger"]["side"] == "LONG"
    assert middle["trigger"]["status"] == "WAIT"
    assert "tested support/resistance" in middle["trigger"]["reason"].lower()


def test_range_distribution_short_uses_signed_regime_route_confidence():
    now = datetime.now(timezone.utc)
    payload = build_range_reversion_payload(
        _location_core(now, "RANGE_DISTRIBUTION", regime_score=-20.0),
        _bearish_location_market_participation(now),
    )

    assert payload["trigger"]["status"] == "READY"
    assert payload["trigger"]["side"] == "SHORT"
    assert payload["confirmation"]["confidence"] == 80.0
    assert payload["trade_plan_validation"]["is_valid"] is True
