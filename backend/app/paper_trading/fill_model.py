from app.trading.trade_plan_engine import price_precision


def build_fill_profile(
    side,
    planned_entry_price,
    stop_loss=None,
    target1=None,
    confidence=50,
    risk_reward=None,
):
    if planned_entry_price is None:
        return {
            "model": "paper_trade_fill_model_v1",
            "side": side,
            "planned_entry_price": None,
            "entry_fill_price": None,
            "entry_slippage_pct": 0,
            "entry_slippage_amount": 0,
            "exit_slippage_pct": 0,
            "exit_slippage_amount": 0,
            "fill_quality": "UNAVAILABLE",
            "effective_risk_reward": None,
            "notes": ["No planned entry price supplied"],
        }

    precision = price_precision(float(planned_entry_price))
    confidence = _clamp(float(confidence if confidence is not None else 50), 0, 100)
    entry_slippage_pct = _entry_slippage_pct(
        planned_entry_price,
        stop_loss,
        confidence,
        risk_reward,
    )
    exit_slippage_pct = round(max(0.00005, entry_slippage_pct * 0.5), 6)
    direction = 1 if str(side).upper() == "LONG" else -1
    entry_fill_price = float(planned_entry_price) * (1 + direction * entry_slippage_pct)
    entry_fill_price = round(entry_fill_price, precision)
    entry_slippage_amount = round(
        abs(entry_fill_price - float(planned_entry_price)),
        precision,
    )
    effective_rr = _effective_risk_reward(
        str(side).upper(),
        entry_fill_price,
        stop_loss,
        target1,
    )

    if entry_slippage_pct <= 0.0004:
        fill_quality = "TIGHT"
    elif entry_slippage_pct <= 0.0008:
        fill_quality = "NORMAL"
    elif entry_slippage_pct <= 0.0015:
        fill_quality = "WIDE"
    else:
        fill_quality = "POOR"

    notes = []
    if confidence < 60:
        notes.append("Lower confidence widens simulated fill")
    if stop_loss is not None and planned_entry_price:
        notes.append("ATR proxy derived from entry-stop distance")
    if risk_reward is not None:
        notes.append("Risk/reward nudges slippage assumptions")

    return {
        "model": "paper_trade_fill_model_v1",
        "side": str(side).upper(),
        "planned_entry_price": round(float(planned_entry_price), precision),
        "entry_fill_price": entry_fill_price,
        "entry_slippage_pct": round(entry_slippage_pct * 100, 4),
        "entry_slippage_amount": entry_slippage_amount,
        "exit_slippage_pct": round(exit_slippage_pct * 100, 4),
        "exit_slippage_amount": round(
            abs(float(planned_entry_price) * exit_slippage_pct),
            precision,
        ),
        "fill_quality": fill_quality,
        "effective_risk_reward": effective_rr,
        "confidence": confidence,
        "notes": notes,
    }


def simulate_exit_fill(trade, trigger_price, trigger_type="TARGET"):
    confidence = _clamp(float(getattr(trade, "confidence", 50) or 50), 0, 100)
    side = str(getattr(trade, "side", "")).upper()
    planned_entry = getattr(trade, "entry_price", None)
    stop_loss = getattr(trade, "stop_loss", None)
    target1 = getattr(trade, "target1", None)
    reference_entry = planned_entry if planned_entry is not None else trigger_price
    base_slippage_pct = _entry_slippage_pct(
        reference_entry,
        stop_loss,
        confidence,
        getattr(trade, "risk_reward", None),
    )
    trigger_factor = 1.25 if trigger_type == "STOP" else 0.6
    exit_slippage_pct = round(max(0.00005, base_slippage_pct * trigger_factor), 6)
    direction = -1 if side == "LONG" else 1
    fill_price = float(trigger_price) * (1 + direction * exit_slippage_pct)
    precision = price_precision(float(trigger_price))
    fill_price = round(fill_price, precision)

    return {
        "trigger_type": trigger_type,
        "trigger_price": round(float(trigger_price), precision),
        "exit_fill_price": fill_price,
        "exit_slippage_pct": round(exit_slippage_pct * 100, 4),
        "exit_slippage_amount": round(
            abs(fill_price - float(trigger_price)),
            precision,
        ),
        "confidence": confidence,
        "side": side,
        "planned_entry_price": planned_entry if planned_entry is not None else reference_entry,
        "stop_loss": stop_loss,
        "target1": target1,
    }


def _entry_slippage_pct(planned_entry_price, stop_loss, confidence, risk_reward):
    entry_price = float(planned_entry_price)
    stop_distance_pct = 0 if stop_loss is None else abs(entry_price - float(stop_loss)) / entry_price
    confidence_penalty = max(0.0, (75 - confidence)) * 0.00001
    volatility_penalty = min(0.001, stop_distance_pct * 0.02)
    rr_penalty = 0.0

    if risk_reward is not None:
        rr_penalty = max(0.0, (2.0 - float(risk_reward))) * 0.0001

    slippage_pct = 0.00015 + confidence_penalty + volatility_penalty + rr_penalty
    return round(_clamp(slippage_pct, 0.00005, 0.003), 6)


def _effective_risk_reward(side, entry_fill_price, stop_loss, target1):
    if stop_loss is None or target1 is None or entry_fill_price is None:
        return None

    entry_fill_price = float(entry_fill_price)
    stop_loss = float(stop_loss)
    target1 = float(target1)

    if side == "LONG":
        risk = abs(entry_fill_price - stop_loss)
        reward = abs(target1 - entry_fill_price)
    else:
        risk = abs(stop_loss - entry_fill_price)
        reward = abs(entry_fill_price - target1)

    if risk == 0:
        return None

    return round(reward / risk, 2)


def _clamp(value, minimum, maximum):
    return max(minimum, min(maximum, float(value)))
