"""Shared frozen-context decision evaluation for API and historical replay."""

from types import SimpleNamespace

from app.engines.derivative_engine import DerivativeEngine
from app.engines.liquidity_engine import LiquidityEngine
from app.engines.smart_money_fusion_engine import SmartMoneyFusionEngine
from app.intelligence.contradiction_engine import analyze_contradictions
from app.risk.risk_engine import RiskEngine
from app.backtesting.replay_parity import build_parity_record


DIRECTIONAL_RISK_RESEARCH_REGIMES = {
    "LONG": {"BULL_PULLBACK", "RANGE_ACCUMULATION"},
    "SHORT": {"BEAR_RALLY", "RANGE_DISTRIBUTION"},
}


def evaluate_frozen_decision(
    symbol,
    timeframe,
    intelligence,
    derivatives,
    *,
    capital=10_000,
    risk_percent=1,
    risk_min_confidence=None,
    risk_confidence_scope=None,
):
    capital = float(capital)
    risk_percent = float(risk_percent)
    intelligence = dict(intelligence or {})
    master_signal = dict(intelligence.get("signal") or {})
    feature = dict(intelligence.get("feature") or {})
    regime = dict(intelligence.get("regime") or {})
    orderflow = dict(intelligence.get("orderflow") or {})
    smc = dict(intelligence.get("smc") or {})
    derivatives = dict(derivatives or {})
    funding = dict(derivatives.get("funding") or {})
    open_interest = dict(derivatives.get("open_interest") or {})

    feature_row = SimpleNamespace(
        Trend=feature.get("trend"),
        TrendScore=feature.get("trend_score"),
        FinalScore=feature.get("final_score"),
        LiquidityScore=feature.get("liquidity_score"),
    )
    regime_row = SimpleNamespace(
        Regime=regime.get("regime"),
        Confidence=regime.get("confidence"),
    )
    orderflow_row = SimpleNamespace(
        FlowSignal=orderflow.get("signal"),
        Confidence=orderflow.get("confidence"),
        BuyerStrength=orderflow.get("buyer_strength"),
        SellerStrength=orderflow.get("seller_strength"),
        Delta=orderflow.get("delta"),
        CVD=orderflow.get("cvd"),
        Absorption=orderflow.get("absorption"),
    )
    smc_row = SimpleNamespace(
        smc_bias=smc.get("bias"),
        confidence=smc.get("confidence"),
        bos_type=(smc.get("bos") or {}).get("direction"),
        liquidity_sweep=(smc.get("sweep") or {}).get("type"),
    )

    funding_rate = funding.get("rate")
    oi_change = open_interest.get("change_pct")
    price_change = intelligence.get("price_change_pct")
    liquidity = LiquidityEngine().analyze(
        symbol,
        funding_rate or 0.0,
        oi_change or 0.0,
        price_change or 0.0,
    )
    derivative = DerivativeEngine().analyze(
        funding_rate=funding_rate,
        open_interest_delta=oi_change,
        long_short_ratio=None,
    )
    smart_money = SmartMoneyFusionEngine().analyze(smc_row, orderflow_row)
    current_price = intelligence.get("current_price")
    previous_price = intelligence.get("previous_price")
    candle_row = (
        SimpleNamespace(close_price=current_price)
        if current_price is not None
        else None
    )
    fresh = {"is_stale": False}
    contradiction = analyze_contradictions(
        symbol=symbol,
        timeframe=timeframe,
        signal=master_signal,
        feature=feature_row,
        regime=regime_row,
        orderflow=orderflow_row,
        smc=smc_row,
        candle=candle_row,
        liquidity=SimpleNamespace(**liquidity),
        derivative=SimpleNamespace(**derivative),
        whale=None,
        smart_money=SimpleNamespace(**smart_money),
        heatmap=None,
        freshness={
            "candle": fresh,
            "feature": fresh,
            "regime": fresh,
            "orderflow": fresh,
            "smc": fresh,
        },
        current_price=current_price,
        previous_price=previous_price,
        price_change_pct=price_change,
        funding_rate=funding_rate,
        open_interest_change_pct=oi_change,
    )

    signal_side = str(master_signal.get("signal") or "").upper()
    regime_name = str(regime.get("regime") or "").upper()
    scope_key = str(risk_confidence_scope or "").upper()
    risk_override_applies = (
        risk_min_confidence is not None
        and scope_key == "DIRECTIONAL_PULLBACK_RANGE"
        and regime_name in DIRECTIONAL_RISK_RESEARCH_REGIMES.get(signal_side, set())
    )
    risk = RiskEngine().analyze(
        symbol=symbol,
        signal=master_signal.get("signal"),
        price=current_price,
        atr=feature.get("atr"),
        confidence=master_signal.get("confidence"),
        capital=capital,
        risk_percent=risk_percent,
        min_confidence=(risk_min_confidence if risk_override_applies else None),
    )
    if risk.get("decision") == "APPROVE" and not contradiction.get("trade_allowed"):
        risk = {
            **risk,
            "decision": "REJECT",
            "reason": (
                "Contradiction gate did not allow the replay signal: "
                f"{contradiction.get('status')}"
            ),
            "position_size": None,
        }

    actionable = str(master_signal.get("signal") or "").upper() in {"LONG", "SHORT"}
    executor_verdict = (
        "WOULD_QUEUE"
        if actionable
        and contradiction.get("trade_allowed")
        and risk.get("decision") == "APPROVE"
        else "BLOCKED"
        if actionable
        else "NO_ACTION"
    )
    decision = {
        "source": "shared_frozen_decision_evaluation",
        "symbol": symbol,
        "timeframe": timeframe,
        "signal": master_signal,
        "contradiction": contradiction,
        "risk": risk,
        "executor": {
            "verdict": executor_verdict,
            "side_effect": "NONE",
            "paper_trade_created": False,
        },
        "leakage_status": "PASS",
    }
    parity_inputs = {
        "symbol": symbol,
        "timeframe": timeframe,
        "intelligence": intelligence,
        "derivatives": derivatives,
        "capital": capital,
        "risk_percent": risk_percent,
    }
    if risk_min_confidence is not None:
        decision["risk_min_confidence"] = float(risk_min_confidence)
        decision["risk_confidence_scope"] = scope_key
        decision["risk_confidence_override_applied"] = risk_override_applies
        parity_inputs["risk_min_confidence"] = float(risk_min_confidence)
        parity_inputs["risk_confidence_scope"] = scope_key
    decision["parity"] = build_parity_record(parity_inputs, decision)
    return decision
