"""Bounded paper execution evidence; sampled prices never imply full tick coverage."""
import json
import math
from datetime import datetime, timezone


EVIDENCE_VERSION = "PAPER_EXIT_EVIDENCE_V1"
MAX_EVIDENCE_BYTES = 8192


def read_evidence(value):
    if isinstance(value, dict):
        return dict(value)
    try:
        result = json.loads(value or "{}")
        return result if isinstance(result, dict) else {}
    except (TypeError, ValueError):
        return {}


def encode_evidence(value):
    """Reject oversized evidence rather than silently dropping cohort identifiers."""
    encoded = json.dumps(value, default=_json_default, allow_nan=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_EVIDENCE_BYTES:
        raise ValueError("Paper execution evidence exceeds bounded storage budget")
    return encoded


def _json_default(value):
    if isinstance(value, datetime):
        return _iso(value)
    raise TypeError(f"Unsupported execution evidence type: {type(value).__name__}")


def entry_evidence_fields(candidate):
    activation = candidate.get("trailing_activation_r")
    if activation is not None:
        activation = float(activation)
        if not math.isfinite(activation) or not 0 <= activation <= 5:
            raise ValueError("Paper trailing activation must be between zero and five R")
    supplied = candidate.get("execution_evidence")
    if supplied is not None and not isinstance(supplied, dict):
        raise ValueError("Paper execution evidence must be an object")
    plan = candidate.get("trade_plan") or {}
    evidence = dict(supplied or {})
    evidence.update({
        "evidence_version": EVIDENCE_VERSION,
        "strategy_id": plan.get("strategy_id"),
        "strategy_version": plan.get("strategy_version"),
        "decision_snapshot_id": plan.get("strategy_decision_snapshot_id"),
        "trailing_activation_r": activation,
    })
    return {"execution_evidence_json": encode_evidence(evidence), "trailing_activation_r": activation}


def classify_exit(trade, trigger_type=None):
    trigger = str(trigger_type or getattr(trade, "exit_reason", None) or "UNKNOWN").upper()
    if trigger not in {"STOP", "STOP_LOSS"}:
        return trigger if trigger in {"TARGET", "TARGET1", "TARGET2", "TIME_EXIT"} else "UNKNOWN"
    if getattr(trade, "target1_hit_at", None) is not None:
        return "PROTECTED_STOP_AFTER_T1"
    initial = _number(getattr(trade, "initial_stop_loss", None))
    active = _number(getattr(trade, "stop_loss", None))
    side = str(getattr(trade, "side", "")).upper()
    if initial is None or active is None or initial <= 0 or active <= 0 or side not in {"LONG", "SHORT"}:
        return "UNKNOWN_STOP"
    if math.isclose(initial, active, rel_tol=1e-9, abs_tol=1e-10):
        return "INITIAL_STOP"
    if (side == "LONG" and active > initial) or (side == "SHORT" and active < initial):
        return "TRAILED_STOP_PRE_T1"
    return "UNKNOWN_STOP"  # A loosened or inconsistent historical stop is not inferred.


def observation_evidence(trade, candle, previous=None):
    """Aggregate only observed excursion bounds, with no tick-by-tick DB rows."""
    evidence = dict(previous or {})
    entry = _number(getattr(trade, "entry_price", None))
    high = _number(getattr(candle, "high_price", None))
    low = _number(getattr(candle, "low_price", None))
    if not entry or high is None or low is None:
        return evidence
    side = str(getattr(trade, "side", "")).upper()
    if side not in {"LONG", "SHORT"}:
        return evidence
    favorable, adverse = ((high - entry, entry - low) if side == "LONG" else (entry - low, high - entry))
    observed = _iso(getattr(candle, "close_time", None) or getattr(candle, "candle_time", None))
    evidence["mfe_percent"] = round(max(float(evidence.get("mfe_percent") or 0), favorable / entry * 100, 0), 6)
    evidence["mae_percent"] = round(max(float(evidence.get("mae_percent") or 0), adverse / entry * 100, 0), 6)
    if observed:
        evidence["first_observed_at"] = min(evidence.get("first_observed_at") or observed, observed)
        evidence["last_observed_at"] = max(evidence.get("last_observed_at") or observed, observed)
    evidence["coverage"] = "OBSERVED_ONLY"
    source = str(getattr(candle, "source", None) or ("LIVE_MARK" if getattr(candle, "live_mark", False) else "CANDLE_RECONCILIATION"))[:100]
    evidence["sources"] = sorted(set(evidence.get("sources") or []) | {source})[:4]
    return evidence


def merge_observations(trade, observations):
    if not observations:
        return
    evidence = read_evidence(getattr(trade, "exit_evidence_json", None))
    current = evidence.get("observations") or {}
    combined = {**current, **observations, "coverage": "OBSERVED_ONLY"}
    for key in ("mfe_percent", "mae_percent"):
        combined[key] = max(float(current.get(key) or 0), float(observations.get(key) or 0))
    for key, fn in (("first_observed_at", min), ("last_observed_at", max)):
        values = [item[key] for item in (current, observations) if item.get(key)]
        if values:
            combined[key] = fn(values)
    combined["sources"] = sorted(set(current.get("sources") or []) | set(observations.get("sources") or []))[:4]
    evidence.update(version=EVIDENCE_VERSION, observations=combined)
    trade.exit_evidence_json = encode_evidence(evidence)


def exit_context(trade, candle, trigger_type):
    observed = getattr(candle, "close_time", None) or getattr(candle, "candle_time", None)
    processed = datetime.now(timezone.utc)
    normalized = _utc(observed)
    return {
        "version": EVIDENCE_VERSION,
        "classification": classify_exit(trade, trigger_type),
        "trigger_type": trigger_type,
        "initial_stop_loss": getattr(trade, "initial_stop_loss", None),
        "active_stop_before_trigger": getattr(trade, "stop_loss", None),
        "target1_complete": getattr(trade, "target1_hit_at", None) is not None,
        "observed_price": getattr(candle, "close_price", None),
        "observed_at": _iso(observed),
        "processed_at": _iso(processed),
        "quote_age_seconds": round((processed - normalized).total_seconds(), 3) if normalized else None,
        "source": str(getattr(candle, "source", None) or ("LIVE_MARK" if getattr(candle, "live_mark", False) else "CANDLE_RECONCILIATION"))[:100],
        "evidence_kind": "LIVE_MARK" if getattr(candle, "live_mark", False) else "CANDLE_OHLC",
        "observations": observation_evidence(trade, candle),
    }


def record_exit_evidence(trade, fill_profile, exit_price):
    fill = fill_profile or {}
    context = fill.get("exit_evidence")
    evidence = read_evidence(getattr(trade, "exit_evidence_json", None))
    if isinstance(context, dict):
        merge_observations(trade, context.get("observations"))
        evidence = read_evidence(getattr(trade, "exit_evidence_json", None))
        evidence.update({key: value for key, value in context.items() if key != "observations"})
    else:
        evidence.update(version=EVIDENCE_VERSION, classification="UNKNOWN", evidence_kind="MISSING_TRIGGER_EVIDENCE")
    evidence.update(exit_fill_price=float(exit_price), trigger_price=fill.get("trigger_price"), slippage_percent=fill.get("exit_slippage_pct"))
    trade.exit_evidence_json = encode_evidence(evidence)


def _number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _utc(value):
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _iso(value):
    normalized = _utc(value)
    return normalized.isoformat() if normalized else None
