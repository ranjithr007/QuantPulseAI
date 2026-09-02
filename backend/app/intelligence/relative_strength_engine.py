"""Cross-sectional relative-strength ranking for the tracked crypto universe."""

from __future__ import annotations


RS_TIMEFRAMES = ("1h", "2h", "4h", "1d")
RS_WEIGHTS = {"1h": 1.0, "2h": 2.0, "4h": 3.0, "1d": 4.0}


def rank_relative_strength(records):
    """Attach a peer-relative score to every watchlist record.

    Each timeframe return is ranked independently so a 1h return is never
    compared directly with a 1d return.  The percentile scores are centred to
    -100..+100 and combined with higher-timeframe weighting.
    """

    rows = list(records or [])
    usable = {}
    for row in rows:
        symbol = str(row.get("symbol") or "").upper()
        performance = row.get("timeframe_performance") or {}
        missing = [
            timeframe
            for timeframe in RS_TIMEFRAMES
            if _optional_number((performance.get(timeframe) or {}).get("return_pct"))
            is None
        ]
        if missing:
            row["relative_strength"] = _unavailable(
                f"Missing return history: {', '.join(missing)}",
                missing,
            )
            continue
        usable[symbol] = {
            timeframe: _optional_number(performance[timeframe]["return_pct"])
            for timeframe in RS_TIMEFRAMES
        }

    if len(usable) < 2:
        for row in rows:
            row["relative_strength"] = _unavailable(
                "At least two symbols with complete return history are required",
                RS_TIMEFRAMES,
            )
            row["rotation"] = _rotation_unavailable(
                "At least two symbols with complete return history are required"
            )
        return rows

    timeframe_scores = {
        timeframe: _centred_percentile_scores(
            {symbol: values[timeframe] for symbol, values in usable.items()}
        )
        for timeframe in RS_TIMEFRAMES
    }
    composite = {}
    weight_total = sum(RS_WEIGHTS.values())
    for symbol in usable:
        composite[symbol] = sum(
            timeframe_scores[timeframe][symbol] * RS_WEIGHTS[timeframe]
            for timeframe in RS_TIMEFRAMES
        ) / weight_total

    ordered = sorted(composite, key=lambda symbol: (-composite[symbol], symbol))
    rank_by_symbol = {
        symbol: 1 + sum(
            1 for other_score in composite.values() if other_score > composite[symbol]
        )
        for symbol in ordered
    }

    for row in rows:
        symbol = str(row.get("symbol") or "").upper()
        if symbol not in usable:
            continue
        score = composite[symbol]
        row["relative_strength"] = {
            "status": "READY",
            "score": round(score, 2),
            "rank": rank_by_symbol[symbol],
            "universe_size": len(usable),
            "benchmark": "TRACKED_UNIVERSE",
            "return_window_bars": 20,
            "timeframes": {
                timeframe: {
                    "return_pct": round(usable[symbol][timeframe], 4),
                    "percentile_score": round(
                        timeframe_scores[timeframe][symbol], 2
                    ),
                    "weight": RS_WEIGHTS[timeframe],
                }
                for timeframe in RS_TIMEFRAMES
            },
            "reason": "Cross-sectional 20-bar performance across 1h, 2h, 4h, and 1d",
            "execution_eligible": False,
            "execution_note": "Relative strength is descriptive and is not a trade trigger",
        }
        row["rotation"] = classify_rotation(row["relative_strength"])
    for row in rows:
        if "rotation" not in row:
            row["rotation"] = _rotation_unavailable(
                (row.get("relative_strength") or {}).get("reason")
                or "Relative-strength evidence is unavailable"
            )
    return rows


def classify_rotation(relative_strength):
    """Map RS level and RS momentum into classic leadership quadrants."""

    if (relative_strength or {}).get("status") != "READY":
        return _rotation_unavailable(
            (relative_strength or {}).get("reason")
            or "Relative-strength evidence is unavailable"
        )
    timeframes = relative_strength.get("timeframes") or {}
    required = [
        timeframe
        for timeframe in RS_TIMEFRAMES
        if _optional_number((timeframes.get(timeframe) or {}).get("percentile_score"))
        is None
    ]
    if required:
        return _rotation_unavailable(
            f"Missing relative-strength momentum: {', '.join(required)}"
        )

    lower = sum(
        float(timeframes[timeframe]["percentile_score"])
        for timeframe in ("1h", "2h")
    ) / 2.0
    higher = sum(
        float(timeframes[timeframe]["percentile_score"])
        for timeframe in ("4h", "1d")
    ) / 2.0
    momentum = (lower - higher) / 2.0
    strength = float(relative_strength.get("score") or 0.0)

    if strength >= 0 and momentum >= 0:
        quadrant = "LEADING"
        reason = "Relative strength is positive and momentum is improving"
    elif strength >= 0:
        quadrant = "WEAKENING"
        reason = "Relative strength remains positive but momentum is fading"
    elif momentum >= 0:
        quadrant = "IMPROVING"
        reason = "Relative strength is negative but momentum is improving"
    else:
        quadrant = "LAGGING"
        reason = "Relative strength is negative and momentum is weakening"

    return {
        "status": "READY",
        "quadrant": quadrant,
        "strength_score": round(strength, 2),
        "momentum_score": round(momentum, 2),
        "lower_timeframe_score": round(lower, 2),
        "higher_timeframe_score": round(higher, 2),
        "reason": reason,
        "execution_eligible": False,
        "execution_note": "Rotation is descriptive and is not a trade trigger",
    }


def _centred_percentile_scores(values):
    ordered = sorted(values.items(), key=lambda item: (item[1], item[0]))
    denominator = len(ordered) - 1
    if denominator == 0:
        return {ordered[0][0]: 0.0}

    scores = {}
    index = 0
    while index < len(ordered):
        end = index
        while end + 1 < len(ordered) and ordered[end + 1][1] == ordered[index][1]:
            end += 1
        average_index = (index + end) / 2.0
        centred = ((average_index / denominator) * 200.0) - 100.0
        for tie_index in range(index, end + 1):
            scores[ordered[tie_index][0]] = centred
        index = end + 1
    return scores


def _unavailable(reason, affected_timeframes):
    return {
        "status": "UNAVAILABLE",
        "score": None,
        "rank": None,
        "universe_size": 0,
        "benchmark": "TRACKED_UNIVERSE",
        "reason": reason,
        "affected_timeframes": list(affected_timeframes),
        "execution_eligible": False,
        "execution_note": "Relative strength is descriptive and is not a trade trigger",
    }


def _rotation_unavailable(reason):
    return {
        "status": "UNAVAILABLE",
        "quadrant": "UNAVAILABLE",
        "strength_score": None,
        "momentum_score": None,
        "reason": reason,
        "execution_eligible": False,
        "execution_note": "Rotation is descriptive and is not a trade trigger",
    }


def _optional_number(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
