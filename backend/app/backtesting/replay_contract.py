"""Shared contracts for leakage-safe historical replay inputs.

The replay engine currently evaluates one selected timeframe.  This module
keeps the official decision stack and as-of filtering in one place so the
multi-timeframe replay can be added without each caller inventing its own
cutoff rules.
"""

from datetime import timezone

from app.governance.evidence_policy import OFFICIAL_ENTRY_TIMEFRAMES
from app.intelligence.multi_timeframe_engine import combine_timeframe_signals
from app.utils.freshness import normalize_timestamp_to_utc


REPLAY_INPUT_CONTRACT_VERSION = "pit_replay_input_v1"


def build_replay_input_contract(timeframe):
    """Describe the replay scope and the currently supported stack policy."""
    timeframe_key = str(timeframe or "").strip().lower()
    official = timeframe_key in set(OFFICIAL_ENTRY_TIMEFRAMES)
    higher = {
        "1h": ["2h", "4h", "1d"],
        "2h": ["4h", "1d"],
        "4h": ["1d"],
        "1d": [],
    }.get(timeframe_key, [])
    return {
        "contract_version": REPLAY_INPUT_CONTRACT_VERSION,
        "timeframe": timeframe_key or None,
        "official_timeframes": list(OFFICIAL_ENTRY_TIMEFRAMES),
        "decision_timeframe": "1h",
        "higher_timeframes": higher,
        "as_of_policy": "FINAL_CLOSED_CANDLES_ONLY",
        "entry_policy": "NEXT_CANDLE_OPEN",
        "intrabar_collision_policy": "STOP_FIRST",
        "status": "PARTIAL_MULTI_TIMEFRAME" if official else "NON_OFFICIAL",
    }


def candles_as_of(candles, as_of_timestamp, *, limit=200):
    """Return final, closed candles whose close is not after ``as_of``.

    The helper accepts ORM rows or mapping-like candle records and always
    returns an ascending list.  It is intentionally pure so replay and parity
    tests can exercise the same cutoff without a database.
    """
    cutoff = normalize_timestamp_to_utc(as_of_timestamp)
    if cutoff is None:
        return []
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=timezone.utc)

    def value(candle, name, fallback=None):
        if isinstance(candle, dict):
            return candle.get(name, fallback)
        return getattr(candle, name, fallback)

    def normalized(value_to_normalize):
        value = normalize_timestamp_to_utc(value_to_normalize)
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    eligible = []
    for candle in candles or []:
        if value(candle, "is_final", True) is False:
            continue
        candle_time = normalized(value(candle, "candle_time", value(candle, "open_time")))
        close_time = normalized(value(candle, "close_time", candle_time))
        if candle_time is None or close_time is None or close_time > cutoff:
            continue
        eligible.append((candle_time, candle))

    eligible.sort(key=lambda item: item[0])
    return [candle for _, candle in eligible[-max(int(limit), 0):]]


def build_point_in_time_stack(
    symbol,
    candles_by_timeframe,
    as_of_timestamp,
    *,
    feature_builder=None,
    intelligence_builder=None,
    history_limit=300,
    minimum_history=50,
):
    """Build the official 1h/2h/4h/1d context from one immutable event cutoff."""
    cutoff = normalize_timestamp_to_utc(as_of_timestamp)
    timeframe_records = []

    for timeframe in OFFICIAL_ENTRY_TIMEFRAMES:
        history = candles_as_of(
            (candles_by_timeframe or {}).get(timeframe),
            cutoff,
            limit=history_limit,
        )
        if len(history) < minimum_history:
            timeframe_records.append(
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "status": "NO_DATA",
                    "signal": "NO_DATA",
                    "bias": "NO_DATA",
                    "direction": "UNKNOWN",
                    "confidence": 0,
                    "score": 0,
                    "candle_count": len(history),
                    "required_candle_count": minimum_history,
                }
            )
            continue

        intelligence = (
            intelligence_builder(
                symbol,
                timeframe,
                history,
                source_timestamp=cutoff,
                effective_timestamp=cutoff,
            )
            if intelligence_builder is not None
            else None
        )
        if intelligence is not None:
            master_signal = dict(intelligence.get("signal") or {})
            signal = str(master_signal.get("signal") or "WAIT")
            bias = str(master_signal.get("bias") or "NEUTRAL")
            confidence = float(master_signal.get("confidence") or 0)
            score = float(master_signal.get("score") or 0)
            final_score = float(
                (intelligence.get("feature") or {}).get("final_score", 50)
            )
        else:
            if feature_builder is None:
                raise ValueError(
                    "feature_builder or intelligence_builder is required"
                )
            feature_contract = feature_builder(
                symbol,
                timeframe,
                history,
                source_timestamp=cutoff,
                effective_timestamp=cutoff,
            )
            feature = (
                feature_contract.get("feature")
                if isinstance(feature_contract, dict) and "feature" in feature_contract
                else feature_contract
            )
            final_score = float((feature or {}).get("final_score", 50))
            signal, bias = _feature_direction(final_score)
            confidence = round(50 + abs(final_score - 50), 2)
            score = round(final_score - 50, 2)

        timeframe_records.append(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "status": "OK",
                "signal": signal,
                "bias": bias,
                "direction": _market_direction(bias, signal),
                "confidence": round(confidence, 2),
                "score": round(score, 2),
                "feature_score": round(final_score, 2),
                "candle_count": len(history),
                "last_candle_time": _candle_time(history[-1]),
                "intelligence": intelligence,
            }
        )

    confirmation = combine_timeframe_signals(timeframe_records)
    ready = all(item["status"] == "OK" for item in timeframe_records)
    return {
        "source": "point_in_time_replay_stack",
        "contract_version": REPLAY_INPUT_CONTRACT_VERSION,
        "symbol": symbol,
        "as_of": cutoff,
        "status": "READY" if ready else "INSUFFICIENT_HISTORY",
        "timeframes_used": list(OFFICIAL_ENTRY_TIMEFRAMES),
        "timeframes": timeframe_records,
        "confirmation": confirmation,
        "component_scope": (
            "CANDLE_DERIVED_FEATURE_REGIME_ORDERFLOW_SMC"
            if intelligence_builder is not None
            else "FEATURE_ONLY"
        ),
        "leakage_status": "PASS",
    }


def _feature_direction(final_score):
    if final_score >= 70:
        return "LONG", "LONG"
    if final_score >= 55:
        return "WAIT", "WEAK_LONG"
    if final_score <= 30:
        return "SHORT", "SHORT"
    if final_score <= 45:
        return "WAIT", "WEAK_SHORT"
    return "WAIT", "NEUTRAL"


def _market_direction(bias, signal=None):
    text = f"{bias or ''} {signal or ''}".upper()
    if any(token in text for token in ("LONG", "BULL", "BUY")):
        return "BULLISH"
    if any(token in text for token in ("SHORT", "BEAR", "SELL")):
        return "BEARISH"
    return "NEUTRAL" if "NO_DATA" not in text else "UNKNOWN"


def _candle_time(candle):
    if isinstance(candle, dict):
        return candle.get("candle_time") or candle.get("open_time")
    return getattr(candle, "candle_time", None) or getattr(candle, "open_time", None)
