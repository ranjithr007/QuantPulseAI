"""Four-timeframe technical market-stage classification.

The stage result is descriptive evidence for the dashboard.  It is deliberately
kept separate from trade eligibility and paper execution.
"""

from __future__ import annotations


STAGE_TIMEFRAMES = ("1h", "2h", "4h", "1d")


def analyze_market_stage(timeframes):
    """Classify one symbol from fresh 1h/2h/4h/1d feature evidence.

    TrendScore is a 0..100 technical feature score.  The higher timeframes are
    used to identify the established phase and the lower timeframes identify
    strengthening or weakening participation inside that phase.
    """

    records = {
        str(item.get("timeframe") or "").lower(): item
        for item in (timeframes or [])
        if isinstance(item, dict)
    }
    missing = [timeframe for timeframe in STAGE_TIMEFRAMES if timeframe not in records]
    if missing:
        return _unavailable(
            "MISSING",
            f"Missing timeframe evidence: {', '.join(missing)}",
            missing,
        )

    stale = []
    invalid = []
    scores = {}
    momentum = {}
    trends = {}

    for timeframe in STAGE_TIMEFRAMES:
        item = records[timeframe]
        freshness = item.get("freshness") or {}
        status = str(item.get("status") or "").upper()
        if freshness.get("is_stale") or status == "STALE":
            stale.append(timeframe)

        score = _optional_number(item.get("feature_trend_score"))
        if score is None or status in {"NO_DATA", "MISSING", "UNAVAILABLE"}:
            invalid.append(timeframe)
        else:
            scores[timeframe] = _clamp(score, 0.0, 100.0)
            momentum[timeframe] = _optional_number(
                item.get("feature_momentum_score")
            )
            trends[timeframe] = str(item.get("feature_trend") or "UNKNOWN").upper()

    if stale:
        return _unavailable(
            "STALE",
            f"Stale timeframe evidence: {', '.join(stale)}",
            stale,
        )
    if invalid:
        return _unavailable(
            "MISSING",
            f"Technical trend evidence unavailable: {', '.join(invalid)}",
            invalid,
        )

    lower_score = (scores["1h"] + scores["2h"]) / 2.0
    higher_score = (scores["4h"] + scores["1d"]) / 2.0
    weighted_score = (
        scores["1h"]
        + (2.0 * scores["2h"])
        + (3.0 * scores["4h"])
        + (4.0 * scores["1d"])
    ) / 10.0
    lower_minus_higher = lower_score - higher_score

    higher_bullish = any(
        token in trends[timeframe]
        for timeframe in ("4h", "1d")
        for token in ("BULL", "UPTREND")
    )
    higher_bearish = any(
        token in trends[timeframe]
        for timeframe in ("4h", "1d")
        for token in ("BEAR", "DOWNTREND")
    )

    if higher_score >= 58.0 and lower_score >= 55.0 and higher_bullish:
        stage = "Stage 2 Uptrend"
        reason = "Higher and lower timeframe technical trends are advancing"
    elif higher_score <= 42.0 and lower_score <= 45.0 and higher_bearish:
        stage = "Stage 4 Downtrend"
        reason = "Higher and lower timeframe technical trends are declining"
    elif lower_minus_higher >= 5.0 or weighted_score < 50.0:
        stage = "Stage 1 Base"
        reason = "Lower timeframes are stabilising or improving against the higher-timeframe trend"
    else:
        stage = "Stage 3 Transition"
        reason = "Lower timeframes are weakening against a mature higher-timeframe trend"

    confidence = _clamp(abs(weighted_score - 50.0) * 2.0, 0.0, 100.0)
    return {
        "status": "READY",
        "stage": stage,
        "score": round((weighted_score - 50.0) * 2.0, 2),
        "confidence": round(confidence, 2),
        "lower_timeframe_score": round(lower_score, 2),
        "higher_timeframe_score": round(higher_score, 2),
        "lower_minus_higher": round(lower_minus_higher, 2),
        "reason": reason,
        "timeframes": {
            timeframe: {
                "trend": trends[timeframe],
                "trend_score": round(scores[timeframe], 2),
                "momentum_score": momentum[timeframe],
            }
            for timeframe in STAGE_TIMEFRAMES
        },
        "execution_eligible": False,
        "execution_note": "Stage analysis is descriptive and is not a trade trigger",
    }


def _unavailable(status, reason, affected_timeframes):
    return {
        "status": status,
        "stage": "UNAVAILABLE",
        "score": None,
        "confidence": 0.0,
        "lower_timeframe_score": None,
        "higher_timeframe_score": None,
        "lower_minus_higher": None,
        "reason": reason,
        "affected_timeframes": list(affected_timeframes),
        "timeframes": {},
        "execution_eligible": False,
        "execution_note": "Stage analysis is descriptive and is not a trade trigger",
    }


def _optional_number(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))
