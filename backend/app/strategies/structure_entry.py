"""Versioned entry-only paper experiments; baseline scoring/exits stay intact."""

import copy
import math
from datetime import datetime, timezone

from app.governance.evidence_policy import OFFICIAL_ENTRY_TIMEFRAMES
from app.intelligence.trade_setup_engine import build_entry_trigger_decision
from app.trading.trade_plan_engine import build_trade_plan
from app.utils.freshness import normalize_timestamp_to_utc
from app.utils.signal_validation import validate_trade_plan_direction


STRUCTURE_PROFILE = "CONFIRMED_PRICE_STRUCTURE_V1"
TIMEFRAME_SECONDS = {"1h": 3600, "2h": 7200, "4h": 14400, "1d": 86400}
MAX_SCAN_AGE_SECONDS = 900
MAX_MARK_AGE_SECONDS = 60
MAX_CLOCK_SKEW_SECONDS = 5
MAX_DRIFT_ATR = 0.5
MAX_LOCATION_ATR = 1.0


def _number(value):
    try:
        if isinstance(value, bool):
            return None
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _timestamp(value):
    try:
        return normalize_timestamp_to_utc(value)
    except (TypeError, ValueError, AttributeError, OverflowError):
        return None


def requires_structure_entry(candidate, quality):
    plan = candidate.get("trade_plan") or {}
    strategy = str(plan.get("strategy_id") or "").upper()
    version = str(plan.get("strategy_version") or "")
    return (quality.get("profile") == STRUCTURE_PROFILE
            or strategy == "CORE_SIGNAL_ENTRY"
            or (strategy == "REGIME_TREND_ENTRY" and version != "regime_trend_entry_v1")
            or (strategy == "MARKET_MOVE_ENTRY" and version != "market_move_entry_v1"))


def revalidate_structure_entry(candidate, mark, *, now=None):
    """Check the recorded closed-candle setup at both mark and simulated fill.

    Output uses diagnostic structure keys, never executor exit-level overrides:
    an entry-only experiment must not silently widen the incumbent stop.
    """
    plan = candidate.get("trade_plan") or {}
    quality = candidate.get("entry_quality") or plan.get("entry_quality") or {}
    measured = {"entry_quality_profile": STRUCTURE_PROFILE, "entry_quality_passed": False}
    if quality.get("profile") != STRUCTURE_PROFILE:
        return measured, "Structure entry candidate is missing its frozen confirmation evidence"
    side = str(candidate.get("side") or plan.get("side") or "").upper()
    timeframe = quality.get("timeframe")
    structure = quality.get("price_structure") or {}
    if (side not in {"LONG", "SHORT"} or quality.get("side") != side
            or timeframe not in TIMEFRAME_SECONDS or structure.get("timeframe") != timeframe
            or (plan.get("entry_timeframe") and plan["entry_timeframe"] != timeframe)):
        return measured, "Structure evidence must match the approved direction and timeframe"
    symbol = str(candidate.get("symbol") or plan.get("symbol") or quality.get("symbol") or "").upper()
    if not symbol or quality.get("symbol") != symbol or structure.get("symbol") != symbol:
        return measured, "Structure evidence must match the approved coin"
    if structure.get("profile") != STRUCTURE_PROFILE or structure.get("status") != "READY":
        return measured, "Confirmed closed-candle price structure is unavailable"
    setup = structure.get(side.lower()) or {}
    measured.update(setup_type=setup.get("setup_type"), structure_timeframe=timeframe,
                    structure_closed_at=structure.get("closed_at"),
                    structure_level=setup.get("level"),
                    structure_invalidation_level=setup.get("invalidation_level"),
                    price_structure=structure.get("structure"))
    if setup.get("confirmed") is not True or setup.get("setup_type") not in {"BREAKOUT_RETEST", "PULLBACK"}:
        return measured, setup.get("reason") or "Bullish/bearish bias is not a confirmed trend entry; wait for breakout/retest or intact-trend pullback"
    current = _timestamp(now or datetime.now(timezone.utc))
    timestamps = {"scan": _timestamp(quality.get("effective_timestamp")),
                  "candle": _timestamp(structure.get("closed_at")),
                  "confirmation": _timestamp(setup.get("confirmed_at")),
                  "mark": _timestamp((mark or {}).get("observed_at"))}
    if current is None or any(value is None for value in timestamps.values()):
        return measured, "Structure confirmation or execution timestamp is unavailable"
    if _timestamp(quality.get("source_timestamp")) != timestamps["candle"]:
        return measured, "Structure and spot inputs must use the same closed candle"
    ages = {key: (current - value).total_seconds() for key, value in timestamps.items()}
    if any(age < -MAX_CLOCK_SKEW_SECONDS for age in ages.values()):
        return measured, "Future-dated structure or execution evidence is invalid"
    if ages["scan"] > MAX_SCAN_AGE_SECONDS or ages["mark"] > MAX_MARK_AGE_SECONDS:
        return measured, "Structure entry requires a fresh scan and execution mark"
    if (ages["candle"] > TIMEFRAME_SECONDS[timeframe] + MAX_SCAN_AGE_SECONDS
            or timestamps["confirmation"] > timestamps["candle"]
            or (timestamps["candle"] - timestamps["confirmation"]).total_seconds() > 2 * TIMEFRAME_SECONDS[timeframe]):
        return measured, "Selected-timeframe closed-candle confirmation is stale"
    price, entry, atr, ema, level, invalidation, close, cvd = (
        _number(value) for value in ((mark or {}).get("mark_price"), quality.get("planned_entry"),
        quality.get("atr"), quality.get("ema20"), setup.get("level"),
        setup.get("invalidation_level"), structure.get("close"), quality.get("spot_cvd_percent")))
    if any(value is None or value <= 0 for value in (price, entry, atr, ema, level, invalidation, close)) or cvd is None:
        return measured, "Structure entry requires finite positive price, ATR, EMA and confirmed levels"
    sign = 1 if side == "LONG" else -1
    drift = abs(price - entry) / atr
    location = sign * (price - level) / atr
    measured.update(entry_drift_atr=drift, entry_boundary_distance_atr=location,
                    entry_evidence_age_seconds=ages["scan"], execution_mark_age_seconds=ages["mark"])
    if sign * (level - invalidation) <= 0 or sign * (close - level) <= 0:
        return measured, "Recorded confirmation levels do not support the approved direction"
    if sign * cvd <= 0:
        return measured, "Spot CVD does not confirm the structure entry direction"
    if drift > MAX_DRIFT_ATR + 1e-9:
        return measured, "Execution price moved more than 0.5 ATR from the confirmed entry plan"
    if not 0 < location <= MAX_LOCATION_ATR + 1e-9:
        return measured, "Execution price left the confirmed one-ATR entry zone"
    if not -1e-9 <= sign * (price - ema) / atr <= MAX_LOCATION_ATR + 1e-9:
        return measured, "Execution price no longer confirms EMA within one ATR"
    measured["entry_quality_passed"] = True
    return measured, None


def build_structure_entry_payload(base_payload, participation, definition, *, rebuild, now=None):
    """Filter *each* baseline timeframe, then select the strongest valid one.

    Rebuild is the same baseline producer with an additional per-timeframe gate.
    It must preserve baseline eligibility, direction, threshold and exit policy.
    """
    current = now or datetime.now(timezone.utc)
    raw = participation or {}
    spots = {item.get("timeframe"): item for item in (raw.get("spot") or {}).get("timeframes") or []}
    quality_by_timeframe, checks = {}, []

    def gate(item, side):
        timeframe = item.get("timeframe")
        spot = spots.get(timeframe) or {}
        entry = item.get("current_price") or item.get("spot_price")
        quality = {"profile": STRUCTURE_PROFILE, "timeframe": timeframe, "side": side,
                   "symbol": base_payload.get("symbol"), "source_timestamp": spot.get("source_timestamp"),
                   "planned_entry": entry,
                   # The participation effective timestamp is the candle close,
                   # not the collector clock. Never refresh it at cache-read time.
                   "effective_timestamp": raw.get("collected_at") or raw.get("effective_timestamp"),
                   "atr": spot.get("atr"), "ema20": spot.get("ema20"),
                   "spot_cvd_percent": spot.get("spot_cvd_percent"),
                   "price_structure": copy.deepcopy(spot.get("price_structure") or {})}
        quality_by_timeframe[timeframe] = quality
        _, reason = revalidate_structure_entry({"side": side, "entry_quality": quality},
                                               {"mark_price": entry, "observed_at": current}, now=current)
        if spot.get("status") != "READY":
            reason = "Fresh selected-timeframe spot evidence is unavailable"
        if spot.get("symbol") != base_payload.get("symbol"):
            reason = "Selected-timeframe spot evidence belongs to a different coin"
        score = _number(item.get("score"))
        if side not in {"LONG", "SHORT"} or score is None or score * (1 if side == "LONG" else -1) < 40:
            reason = "Selected-timeframe direction score must reach +/-40"
        checks.append({"timeframe": timeframe, "name": "confirmed_price_structure",
                       "passed": reason is None, "message": reason or "Closed-candle trend entry confirmed"})
        return reason is None

    payload = rebuild(gate)
    baseline_ready = ((base_payload.get("trigger") or {}).get("status") == "READY"
                      and (base_payload.get("trade_plan_validation") or {}).get("is_valid") is True
                      and bool(base_payload.get("trade_plan")))
    if not baseline_ready:
        payload = copy.deepcopy(base_payload)
    trigger = payload.get("trigger") or {}
    timeframe = trigger.get("entry_timeframe")
    quality = quality_by_timeframe.get(timeframe) or {}
    plan = payload.get("trade_plan")
    if plan:
        quality["planned_entry"] = plan.get("entry")
    evidence = {"entry_quality_profile": STRUCTURE_PROFILE,
                "exit_management_profile": "IMMEDIATE_TRAIL_V1",
                "experiment_version": definition["version"], "paper_only": True}
    payload.update(entry_quality=quality, execution_evidence=evidence, trailing_activation_r=0.0)
    payload["trigger"] = {**trigger, "structure_candidates": checks}
    if trigger.get("status") != "READY" and baseline_ready:
        failure = next((item["message"] for item in checks if not item["passed"]), None)
        if failure:
            payload["trigger"]["reason"] = failure
    if plan:
        plan.update(entry_quality=quality, execution_evidence=evidence, trailing_activation_r=0.0)
    # Selection may round a price or construct a new plan: recheck that exact plan.
    if trigger.get("status") == "READY":
        _, reason = revalidate_structure_entry({"side": trigger.get("side"), "entry_quality": quality},
                                               {"mark_price": (plan or {}).get("entry"), "observed_at": current}, now=current)
        if reason:
            payload["trigger"].update(status="WAIT", side=None, reason=reason)
            payload["trade_plan_validation"] = {"is_valid": False, "errors": [reason]}
    return payload


def rebuild_core_entry_payload(base_payload, gate):
    payload = copy.deepcopy(base_payload)
    timeframes = payload.get("timeframes") or []
    for item in timeframes:
        score = _number(item.get("score"))
        side = "LONG" if score is not None and score >= 40 else "SHORT" if score is not None and score <= -40 else None
        if side and not gate(item, side):
            item["contradiction"] = {**(item.get("contradiction") or {}), "trade_allowed": False,
                                     "status": "INVALIDATED", "reasons": ["Price structure has not confirmed this entry"]}
    trigger = build_entry_trigger_decision(payload.get("confirmation") or {}, timeframes)
    payload["trigger"] = trigger
    if tuple(item.get("timeframe") for item in timeframes) != tuple(OFFICIAL_ENTRY_TIMEFRAMES):
        trigger.update(status="WAIT", side=None, reason="All governed timeframes must be scanned")
    selected = next((item for item in timeframes if item.get("timeframe") == trigger.get("entry_timeframe")), {})
    plan = None
    if trigger.get("status") == "READY":
        # Same core plan producer, selected timeframe and score; no exit experiment here.
        plan = copy.deepcopy(selected.get("trade_plan"))
        if not plan:
            plan = build_trade_plan(trigger["side"], selected.get("current_price"),
                                    confidence=abs(float(selected.get("score") or 0)),
                                    symbol=payload["symbol"], timeframe=selected.get("timeframe"))
    payload["trade_plan"] = plan
    payload["trade_plan_validation"] = validate_trade_plan_direction(
        trigger.get("side"), (plan or {}).get("entry"), (plan or {}).get("target1")) if plan else {
            "is_valid": False, "errors": [trigger.get("reason") or "No confirmed core entry"]}
    return payload
