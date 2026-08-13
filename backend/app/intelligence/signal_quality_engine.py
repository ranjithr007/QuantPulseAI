
from app.governance.evidence_policy import MIN_ENTRY_CONFIDENCE


def _get_value(obj, *names):
    for name in names:
        value = getattr(obj, name, None)
        if value is not None:
            return value
    return None


def validate_signal(signal, confidence, trade_plan, regime, orderflow, smc):

    score = 0

    warnings = []

    # Confidence check

    if confidence >= MIN_ENTRY_CONFIDENCE:

        score += 20

    else:

        warnings.append("Low confidence")

    # Risk reward

    if trade_plan and trade_plan["risk_reward"] >= 2:

        score += 20

    else:

        warnings.append("Poor risk reward")

    # Regime alignment

    if regime:

        regime_state = _get_value(regime, "Regime", "regime")

        if signal == "LONG" and regime_state == "TRENDING_BULL":

            score += 20

        elif signal == "SHORT" and regime_state == "TRENDING_BEAR":

            score += 20

        else:

            warnings.append("Regime mismatch")

    # Orderflow confirmation

    if orderflow:

        flow_signal = _get_value(orderflow, "FlowSignal", "flow_signal")

        if signal == "LONG" and flow_signal == "BUYERS_CONTROL":

            score += 20

        elif signal == "SHORT" and flow_signal == "SELLERS_CONTROL":

            score += 20

        else:

            warnings.append("Orderflow conflict")

    # SMC confirmation

    if smc:

        if signal == smc.smc_bias:

            score += 20

        else:

            warnings.append("SMC conflict")

    # Decision

    if score >= 80:

        decision = "TAKE_TRADE"

    elif score >= 50:

        decision = "WAIT_CONFIRMATION"

    else:

        decision = "AVOID"

    return {"quality_score": score, "decision": decision, "warnings": warnings}
