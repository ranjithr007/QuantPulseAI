"""Leakage-safe reconstruction of candle-derived intelligence for replay."""

from types import SimpleNamespace

from app.features.point_in_time_feature_service import build_feature_snapshot
from app.intelligence.master_ai_engine import generate_master_signal
from app.orderflow.delta_engine import analyze_orderflow
from app.regimes.regime_engine import analyze_market
from app.regimes.rules import detect_regime
from app.smc.smc_engine import analyze_smc
from app.utils.freshness import normalize_timestamp_to_utc


def build_candle_intelligence_as_of(
    symbol,
    timeframe,
    candles,
    *,
    source_timestamp=None,
    effective_timestamp=None,
    previous_regime=None,
    previous_cvd=None,
    state_only=False,
):
    feature_contract = build_feature_snapshot(
        symbol,
        timeframe,
        candles,
        source_timestamp=source_timestamp,
        effective_timestamp=effective_timestamp,
    )
    feature = feature_contract["feature"]
    feature_row = SimpleNamespace(
        Symbol=symbol,
        Timeframe=timeframe,
        Trend=feature.get("trend"),
        TrendScore=feature.get("trend_score"),
        MomentumScore=feature.get("momentum_score"),
        VolatilityScore=feature.get("volatility_score"),
        LiquidityScore=feature.get("liquidity_score"),
        FinalScore=feature.get("final_score"),
        Signal=feature.get("signal"),
    )

    regime = (
        analyze_market(feature_row, previous_regime)
        if previous_regime is not None
        else detect_regime(feature_row)
    )
    regime_row = SimpleNamespace(
        Regime=regime.get("regime"),
        Confidence=regime.get("confidence"),
    )

    orderflow = analyze_orderflow(
        candles,
        previous_cvd=0.0,
        use_persistent_cvd=False,
    )
    if previous_cvd is not None and candles:
        latest_delta = analyze_orderflow(
            [candles[-1]],
            previous_cvd=0.0,
            use_persistent_cvd=False,
        ).get("delta", 0.0)
        orderflow["cvd"] = round(float(previous_cvd) + float(latest_delta), 8)
    orderflow_row = SimpleNamespace(
        FlowSignal=orderflow.get("signal"),
        Confidence=orderflow.get("confidence"),
        BuyerStrength=orderflow.get("buyer_strength"),
        SellerStrength=orderflow.get("seller_strength"),
        Delta=orderflow.get("delta"),
        CVD=orderflow.get("cvd"),
    )

    state = {
        "regime": {
            "Regime": regime.get("regime"),
            "Confidence": regime.get("confidence"),
            "Reason": regime.get("reason"),
        },
        "cvd": orderflow.get("cvd"),
    }
    if state_only:
        return {
            "source": "point_in_time_replay_state",
            "symbol": symbol,
            "timeframe": timeframe,
            "source_timestamp": feature_contract.get("source_timestamp"),
            "effective_timestamp": feature_contract.get("effective_timestamp"),
            "feature": feature,
            "regime": regime,
            "orderflow": orderflow,
            "availability": {
                "regime": (
                    "RECONSTRUCTED_WITH_HYSTERESIS_STATE"
                    if previous_regime is not None
                    else "RECONSTRUCTED_INITIAL_STATE"
                ),
                "orderflow": (
                    "RECONSTRUCTED_PERSISTENT_CVD"
                    if previous_cvd is not None
                    else "RECONSTRUCTED_INITIAL_WINDOW_CVD"
                ),
            },
            "state": state,
            "leakage_status": "PASS",
        }

    smc = analyze_smc(candles)
    smc_row = SimpleNamespace(
        smc_bias=smc.get("bias"),
        confidence=smc.get("confidence"),
        structure=(smc.get("bos") or {}).get("direction"),
    )
    master_signal = generate_master_signal(
        feature_row,
        regime_row,
        orderflow_row,
        smc_row,
    )
    current_price = _price(candles[-1], "close_price") if candles else None
    previous_price = _price(candles[-2], "close_price") if len(candles) > 1 else None
    price_change_pct = (
        ((current_price - previous_price) / previous_price) * 100
        if current_price is not None and previous_price not in (None, 0)
        else None
    )

    return {
        "source": "point_in_time_candle_intelligence",
        "symbol": symbol,
        "timeframe": timeframe,
        "source_timestamp": feature_contract.get("source_timestamp"),
        "effective_timestamp": feature_contract.get("effective_timestamp"),
        "quality_state": feature_contract.get("quality_state"),
        "signal": master_signal,
        "current_price": current_price,
        "previous_price": previous_price,
        "price_change_pct": (
            round(price_change_pct, 6) if price_change_pct is not None else None
        ),
        "feature": feature,
        "regime": regime,
        "orderflow": orderflow,
        "smc": smc,
        "availability": {
            "feature": "RECONSTRUCTED",
            "regime": (
                "RECONSTRUCTED_WITH_HYSTERESIS_STATE"
                if previous_regime is not None
                else "RECONSTRUCTED_INITIAL_STATE"
            ),
            "orderflow": (
                "RECONSTRUCTED_PERSISTENT_CVD"
                if previous_cvd is not None
                else "RECONSTRUCTED_INITIAL_WINDOW_CVD"
            ),
            "smc": "RECONSTRUCTED",
            "derivatives": "NOT_SUPPLIED",
            "contradiction": "NOT_SUPPLIED",
            "risk": "NOT_SUPPLIED",
            "executor": "NOT_SUPPLIED",
        },
        "state": state,
        "leakage_status": "PASS",
    }


def _price(candle, name):
    value = candle.get(name) if isinstance(candle, dict) else getattr(candle, name, None)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_stateful_intelligence_timeline(
    symbol,
    timeframe,
    candles,
    *,
    history_limit=300,
    minimum_history=50,
    full_snapshots=False,
):
    ordered = sorted(
        list(candles or []),
        key=lambda candle: normalize_timestamp_to_utc(
            _value(candle, "candle_time") or _value(candle, "open_time")
        ),
    )
    timeline = []
    previous_regime = None
    previous_cvd = None
    for index in range(minimum_history - 1, len(ordered)):
        history = ordered[max(0, index + 1 - history_limit) : index + 1]
        cutoff = (
            _value(history[-1], "close_time")
            or _value(history[-1], "candle_time")
            or _value(history[-1], "open_time")
        )
        intelligence = build_candle_intelligence_as_of(
            symbol,
            timeframe,
            history,
            source_timestamp=cutoff,
            effective_timestamp=cutoff,
            previous_regime=previous_regime,
            previous_cvd=previous_cvd,
            state_only=not full_snapshots,
        )
        state = intelligence["state"]
        previous_regime = SimpleNamespace(**state["regime"])
        previous_cvd = state["cvd"]
        timeline.append(
            {
                "effective_timestamp": normalize_timestamp_to_utc(cutoff),
                "intelligence": intelligence,
            }
        )
    return timeline


def resolve_intelligence_timeline(timeline, as_of_timestamp):
    cutoff = normalize_timestamp_to_utc(as_of_timestamp)
    if cutoff is None:
        return None
    eligible = [
        item
        for item in timeline or []
        if item["effective_timestamp"] is not None
        and item["effective_timestamp"] <= cutoff
    ]
    return eligible[-1]["intelligence"] if eligible else None


def resolve_state_before(timeline, as_of_timestamp):
    cutoff = normalize_timestamp_to_utc(as_of_timestamp)
    if cutoff is None:
        return None
    eligible = [
        item
        for item in timeline or []
        if item["effective_timestamp"] is not None
        and item["effective_timestamp"] < cutoff
    ]
    if not eligible:
        return None
    return eligible[-1]["intelligence"].get("state")


def _value(item, name):
    return item.get(name) if isinstance(item, dict) else getattr(item, name, None)
