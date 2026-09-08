"""Frozen, paper-only entry experiment gates; scores are never rewritten."""

import copy
import math
from datetime import datetime, timezone

from app.utils.freshness import normalize_timestamp_to_utc


ENTRY_PROFILE = "MARKET_MOVE_RETEST_V1"
MAX_ENTRY_EVIDENCE_AGE_SECONDS = 15 * 60
MAX_MARK_AGE_SECONDS = 60
MAX_CLOCK_SKEW_SECONDS = 5
MAX_DRIFT_ATR = 0.5
MAX_EMA_DISTANCE_ATR = 1.0
MAX_BOUNDARY_DISTANCE_ATR = 1.0
STRUCTURE_BUFFER_ATR = 0.25
MAX_STRUCTURE_STOP_ATR = 2.5


def build_market_move_experiment_payload(base_payload, market_participation, *, entry_only):
    """Clone one incumbent decision, changing exactly the requested experiment."""
    payload = copy.deepcopy(base_payload)
    plan = payload.get("trade_plan")
    trigger = payload.get("trigger") or {}
    side = trigger.get("side")
    timeframe = trigger.get("entry_timeframe")
    selected = next((item for item in payload.get("timeframes") or []
                     if item.get("timeframe") == timeframe), {})
    quality = {
        "profile": ENTRY_PROFILE if entry_only else "MARKET_MOVE_BASELINE_V1",
        "side": side,
        "planned_entry": (plan or {}).get("entry"),
        "effective_timestamp": (market_participation or {}).get("effective_timestamp"),
    }
    if entry_only:
        zone = selected.get("support" if side == "LONG" else "resistance") or {}
        quality.update({
            "atr": selected.get("atr"), "ema20": selected.get("ema20"),
            "structure_level": zone.get("lower" if side == "LONG" else "upper"),
            "tested_rejection": zone.get("latest_rejected") is True and _number(zone.get("tests"), 0) >= 2,
            "spot_cvd_percent": selected.get("spot_cvd_percent"),
            "max_drift_atr": MAX_DRIFT_ATR,
            "max_ema_distance_atr": MAX_EMA_DISTANCE_ATR,
            "max_boundary_distance_atr": MAX_BOUNDARY_DISTANCE_ATR,
            "structure_buffer_atr": STRUCTURE_BUFFER_ATR,
            "max_structure_stop_atr": MAX_STRUCTURE_STOP_ATR,
        })
    experiment = {
        "entry_quality_profile": quality["profile"],
        "exit_management_profile": "IMMEDIATE_TRAIL_V1" if entry_only else "DELAYED_TRAIL_1R_V1",
        "experiment_version": "market_move_entry_v1" if entry_only else "market_move_exit_v1",
        "paper_only": True,
    }
    payload["entry_quality"] = quality
    payload["execution_evidence"] = experiment
    payload["trailing_activation_r"] = 0.0 if entry_only else 1.0
    if plan is not None:
        plan.update(entry_quality=quality, execution_evidence=experiment,
                    trailing_activation_r=payload["trailing_activation_r"])
    # Never rescue an ineligible incumbent or invent missing plan evidence.
    if entry_only and trigger.get("status") == "READY" and plan is not None:
        _, reason = revalidate_entry_candidate(
            {"side": side, "entry_quality": quality},
            {"mark_price": plan.get("entry"), "observed_at": datetime.now(timezone.utc)},
        )
        if reason:
            payload["trigger"] = {**trigger, "status": "WAIT", "side": None, "reason": reason}
            validation = payload.get("trade_plan_validation") or {}
            payload["trade_plan_validation"] = {
                **validation, "is_valid": False,
                "errors": list(dict.fromkeys(list(validation.get("errors") or []) + [reason])),
            }
    return payload


def revalidate_entry_candidate(candidate, mark, *, now=None):
    """Return (measured evidence, blocker) at the final execution boundary.

    Root executor owns fresh-mark fetching, repricing, account risk and fills.
    Missing experiment metadata fails closed for the entry-only strategy.
    Distances are in selected-timeframe ATR, not arbitrary quote-currency points.
    """
    plan = candidate.get("trade_plan") or {}
    quality = candidate.get("entry_quality") or plan.get("entry_quality") or {}
    from app.strategies.structure_entry import requires_structure_entry, revalidate_structure_entry
    if requires_structure_entry(candidate, quality):
        return revalidate_structure_entry(candidate, mark, now=now)
    required = str(plan.get("strategy_id") or "").upper() == "MARKET_MOVE_ENTRY" or quality.get("profile") == ENTRY_PROFILE
    if not required:
        return {}, None
    evidence = {"entry_quality_profile": ENTRY_PROFILE, "entry_quality_passed": False}
    if quality.get("profile") != ENTRY_PROFILE:
        return evidence, "Entry candidate is missing its frozen entry-quality evidence"
    side = str(candidate.get("side") or plan.get("side") or "").upper()
    if side not in {"LONG", "SHORT"} or quality.get("side") != side:
        return evidence, "Entry-quality direction does not match the approved side"
    timestamp = _timestamp(quality.get("effective_timestamp"))
    mark_timestamp = _timestamp((mark or {}).get("observed_at"))
    current = _timestamp(now or datetime.now(timezone.utc))
    if timestamp is None or mark_timestamp is None or current is None:
        return evidence, "Entry-quality or execution timestamp is unavailable"
    evidence_age = (current - timestamp).total_seconds()
    mark_age = (current - mark_timestamp).total_seconds()
    evidence.update(entry_evidence_age_seconds=evidence_age, execution_mark_age_seconds=mark_age)
    if not -MAX_CLOCK_SKEW_SECONDS <= evidence_age <= MAX_ENTRY_EVIDENCE_AGE_SECONDS:
        return evidence, "Entry-location evidence is stale; wait for a fresh retest scan"
    if not -MAX_CLOCK_SKEW_SECONDS <= mark_age <= MAX_MARK_AGE_SECONDS:
        return evidence, "Entry candidate requires a fresh execution mark"
    price = _number((mark or {}).get("mark_price"))
    entry = _number(quality.get("planned_entry"))
    atr = _number(quality.get("atr"))
    ema = _number(quality.get("ema20"))
    structure = _number(quality.get("structure_level"))
    cvd = _number(quality.get("spot_cvd_percent"))
    if any(value is None or value <= 0 for value in (price, entry, atr, ema, structure)) or cvd is None:
        return evidence, "Entry candidate requires finite price, ATR, EMA, structure and spot CVD evidence"
    if quality.get("tested_rejection") is not True:
        return evidence, "Entry candidate requires a tested support/resistance rejection"
    sign = 1 if side == "LONG" else -1
    drift = abs(price - entry) / atr
    ema_distance = sign * (price - ema) / atr
    structure_distance = sign * (price - structure) / atr
    evidence.update(entry_drift_atr=drift, entry_ema_distance_atr=ema_distance,
                    entry_boundary_distance_atr=structure_distance,
                    execution_structure_level=structure, execution_atr=atr)
    if sign * cvd <= 0:
        return evidence, "Spot CVD does not confirm the entry direction"
    if drift > MAX_DRIFT_ATR + 1e-9:
        return evidence, "Execution price moved more than 0.5 ATR from the retest plan"
    if not -1e-9 <= ema_distance <= MAX_EMA_DISTANCE_ATR + 1e-9:
        return evidence, "Execution price no longer confirms EMA within one ATR"
    if not 0 < structure_distance <= MAX_BOUNDARY_DISTANCE_ATR + 1e-9:
        return evidence, "Execution price is outside the confirmed one-ATR boundary entry zone"
    if structure_distance + STRUCTURE_BUFFER_ATR > MAX_STRUCTURE_STOP_ATR:
        return evidence, "Structure invalidation requires more than the allowed 2.5 ATR stop"
    evidence["entry_quality_passed"] = True
    return evidence, None


def _number(value, fallback=None):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return fallback
    return number if math.isfinite(number) else fallback


def _timestamp(value):
    try:
        return normalize_timestamp_to_utc(value)
    except (TypeError, ValueError, AttributeError, OverflowError):
        return None
