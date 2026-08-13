from app.trading.trade_plan_engine import price_precision
from app.trading.futures_cost_model import estimate_entry_slippage_rate
from app.trading.futures_cost_model import estimate_slippage_rates
from app.trading.futures_cost_model import trade_cost_profile
from app.trading.futures_cost_model import DEFAULT_FEE_BPS


def build_fill_profile(
    side,
    planned_entry_price,
    stop_loss=None,
    target1=None,
    confidence=50,
    risk_reward=None,
    fee_bps=DEFAULT_FEE_BPS,
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
            "fee_bps": float(fee_bps),
            "estimated_round_trip_fee_percent": round(float(fee_bps) * 2 / 100, 4),
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
    slippage = estimate_slippage_rates(
        planned_entry_price,
        stop_loss,
        confidence=confidence,
        risk_reward=risk_reward or 2,
    )
    exit_slippage_pct = slippage["target"]
    direction = 1 if str(side).upper() == "LONG" else -1
    entry_fill_price = float(planned_entry_price) * (1 + direction * entry_slippage_pct)
    entry_fill_price = round(entry_fill_price, precision)
    entry_slippage_amount = round(
        abs(entry_fill_price - float(planned_entry_price)),
        precision,
    )
    cost_profile = None
    if stop_loss is not None and target1 is not None:
        cost_profile = trade_cost_profile(
            str(side).upper(),
            planned_entry_price,
            stop_loss,
            target1,
            confidence=confidence,
            fee_bps=fee_bps,
            slippage=slippage,
        )
    effective_rr = (
        cost_profile["net_risk_reward"] if cost_profile is not None else None
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
        "gross_risk_reward": (
            cost_profile["gross_risk_reward"] if cost_profile is not None else None
        ),
        "net_reward_amount": (
            round(cost_profile["net_reward"], precision)
            if cost_profile is not None
            else None
        ),
        "net_loss_amount": (
            round(cost_profile["net_loss"], precision)
            if cost_profile is not None
            else None
        ),
        "estimated_stop_fill_price": (
            round(cost_profile["stop_fill"], precision)
            if cost_profile is not None
            else None
        ),
        "estimated_target_fill_price": (
            round(cost_profile["target_fill"], precision)
            if cost_profile is not None
            else None
        ),
        "fee_bps": float(fee_bps),
        "estimated_round_trip_fee_percent": round(float(fee_bps) * 2 / 100, 4),
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
    slippage = estimate_slippage_rates(
        reference_entry,
        stop_loss,
        confidence=confidence,
        risk_reward=getattr(trade, "risk_reward", None) or 2,
    )
    exit_slippage_pct = (
        slippage["stop"] if trigger_type == "STOP" else slippage["target"]
    )
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
    return estimate_entry_slippage_rate(
        planned_entry_price,
        stop_loss,
        confidence=confidence,
        risk_reward=risk_reward or 2,
    )


def _clamp(value, minimum, maximum):
    return max(minimum, min(maximum, float(value)))
