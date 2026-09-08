"""Closed-candle price structure, independent of scores and execution policy.

Pivots require two complete bars on either side. A pivot may be used only on a
subsequent bar, never on either of the bars needed to confirm that pivot. All
event thresholds use ATR available before the event, not a later ATR. The
returned timestamps identify the actual source/trigger closes; callers own
timeframe-aware freshness checks. No clock-based age cutoff is applied here.
"""

from collections.abc import Mapping
from datetime import datetime, timezone
from math import isfinite


PROFILE = "CONFIRMED_PRICE_STRUCTURE_V1"
MINIMUM_BARS = 25
ATR_PERIOD = 14
PIVOT_WING = 2
RECENT_TRIGGER_BARS = 3
MAX_RETEST_BARS = 5
BREAKOUT_ATR_BUFFER = 0.05
RETEST_ATR_TOLERANCE = 0.25
COMPRESSION_RANGE_ATR = 1.5
TIMEFRAME_SECONDS = {"1h": 3600, "2h": 7200, "4h": 14400, "1d": 86400}


def build_price_structure(candles, timeframe, *, now=None):
    """Return JSON-safe, fail-closed evidence for one final spot-candle series.

    Final bars must explicitly have ``is_final=True`` and matching symbol and
    timeframe. Explicitly forming bars are excluded; an interior forming bar
    therefore leaves a gap and cannot silently bridge missing history. UTC
    datetimes (including database-naive UTC), ISO strings and Unix seconds or
    milliseconds are accepted. Inclusive exchange close times are supported.
    """
    result = {
        "profile": PROFILE,
        "symbol": None,
        "timeframe": timeframe if isinstance(timeframe, str) else None,
        "status": "UNAVAILABLE",
        "closed_at": None,
        "close": None,
        "atr": None,
        "structure": "RANGE",
        "long": _no_setup("INVALID_CANDLE_HISTORY"),
        "short": _no_setup("INVALID_CANDLE_HISTORY"),
    }
    if not isinstance(timeframe, str) or timeframe not in TIMEFRAME_SECONDS:
        return _unavailable(result, "UNSUPPORTED_TIMEFRAME")
    clock = _timestamp(now) if now is not None else datetime.now(timezone.utc)
    if clock is None:
        return _unavailable(result, "INVALID_EVALUATION_TIME")
    bars, error = _validated_bars(candles, timeframe, clock)
    if error:
        return _unavailable(result, error)
    if bars:
        result.update(symbol=bars[-1]["symbol"], closed_at=bars[-1]["closed_at"], close=bars[-1]["close"])
    if len(bars) < MINIMUM_BARS:
        return _unavailable(result, "INSUFFICIENT_FINAL_HISTORY")
    atrs = _atr_series(bars)
    if not _positive(atrs[-1]):
        return _unavailable(result, "NON_POSITIVE_ATR")
    result.update(status="READY", atr=atrs[-1])

    bullish, long_setup = _directional_evidence(bars, atrs, 1)
    bearish, short_setup = _directional_evidence(bars, atrs, -1)
    compressed = max(bar["high"] for bar in bars[-10:]) - min(
        bar["low"] for bar in bars[-10:]
    ) <= COMPRESSION_RANGE_ATR * atrs[-1]
    if compressed:
        if long_setup["setup_type"] == "PULLBACK":
            long_setup = _no_setup("COMPRESSION_REQUIRES_CONFIRMED_BREAKOUT")
        if short_setup["setup_type"] == "PULLBACK":
            short_setup = _no_setup("COMPRESSION_REQUIRES_CONFIRMED_BREAKOUT")
    if long_setup["confirmed"] and short_setup["confirmed"]:
        # Conflicting recent events do not constitute a directional entry.
        long_setup = _no_setup("CONFLICTING_PRICE_STRUCTURE")
        short_setup = _no_setup("CONFLICTING_PRICE_STRUCTURE")
    elif long_setup["confirmed"]:
        result["structure"] = "BULLISH"
    elif short_setup["confirmed"]:
        result["structure"] = "BEARISH"
    elif compressed:
        result["structure"] = "COMPRESSION"
    elif bullish and not bearish:
        result["structure"] = "BULLISH"
    elif bearish and not bullish:
        result["structure"] = "BEARISH"
    result.update(long=long_setup, short=short_setup)
    return result


def _directional_evidence(source, atrs, sign):
    # Reflect shorts around zero so both directions follow exactly the same
    # structural/temporal rules, with actual positive prices restored on output.
    bars = [
        {
            "open": sign * bar["open"],
            "close": sign * bar["close"],
            "high": bar["high"] if sign == 1 else -bar["low"],
            "low": bar["low"] if sign == 1 else -bar["high"],
            "closed_at": bar["closed_at"],
        }
        for bar in source
    ]
    highs = _pivots(bars, "high")
    lows = _pivots(bars, "low")
    count = len(bars)
    current_trend = _trend_context(bars, atrs, highs, lows, count)
    recent_start = count - RECENT_TRIGGER_BARS
    event_start = max(ATR_PERIOD + 1, recent_start - MAX_RETEST_BARS)
    matches = []

    for breakout in range(event_start, count - 1):
        known_highs = [pivot for pivot in highs if pivot["known_at"] < breakout]
        if not known_highs or not _positive(atrs[breakout - 1]):
            continue
        pivot = known_highs[-1]
        level = pivot["value"]
        buffer = atrs[breakout - 1] * BREAKOUT_ATR_BUFFER
        tolerance = atrs[breakout - 1] * RETEST_ATR_TOLERANCE
        if not (bars[breakout - 1]["close"] <= level + buffer < bars[breakout]["close"]):
            continue
        if any(
            bar["close"] > level + buffer
            for bar in bars[pivot["known_at"] + 1:breakout]
        ):
            continue
        if any(
            bar["low"] < level - tolerance or bar["close"] <= level
            for bar in bars[breakout + 1:]
        ) or bars[-1]["close"] <= level + buffer:
            continue
        for retest in range(max(breakout + 1, recent_start), min(count, breakout + MAX_RETEST_BARS + 1)):
            bar = bars[retest]
            if level - tolerance <= bar["low"] <= level + tolerance and bar["close"] > level + buffer:
                matches.append((retest, _setup(
                    "BREAKOUT_RETEST", level, level - tolerance,
                    bar["closed_at"], sign,
                    "CLOSED_BREAKOUT_AND_LATER_RETEST_HELD",
                )))

    # Pullbacks need an already established HH+HL trend (LH+LL for shorts),
    # intact both before the touch and now. Higher lows on their own cannot pass.
    if current_trend:
        for touch in range(event_start, count - 1):
            context = _trend_context(bars, atrs, highs, lows, touch)
            if not context or not _positive(atrs[touch - 1]):
                continue
            level = context["level"]
            buffer = atrs[touch - 1] * BREAKOUT_ATR_BUFFER
            tolerance = atrs[touch - 1] * RETEST_ATR_TOLERANCE
            if not level - tolerance <= bars[touch]["low"] <= level + tolerance:
                continue
            if any(bar["low"] < level - tolerance for bar in bars[touch:]):
                continue
            if bars[-1]["close"] <= level + buffer:
                continue
            for recovery in range(max(touch + 1, recent_start), min(count, touch + MAX_RETEST_BARS + 1)):
                bar = bars[recovery]
                if (
                    bar["close"] > bar["open"]
                    and bar["close"] > bars[recovery - 1]["close"] + buffer
                    and bar["close"] > bars[touch]["close"] + buffer
                    and bar["close"] > level + buffer
                ):
                    matches.append((recovery, _setup(
                        "PULLBACK", level, level - tolerance,
                        bar["closed_at"], sign,
                        "ESTABLISHED_SWING_TREND_PULLBACK_RECOVERED",
                    )))
    if matches:
        # Prefer the latest confirmation, then explicit breakout acceptance.
        return bool(current_trend), max(
            matches, key=lambda item: (item[0], item[1]["setup_type"] == "BREAKOUT_RETEST")
        )[1]
    return bool(current_trend), _no_setup("NO_RECENT_CONFIRMED_BREAKOUT_RETEST_OR_PULLBACK")


def _trend_context(bars, atrs, highs, lows, before):
    known_highs = [pivot for pivot in highs if pivot["known_at"] < before]
    known_lows = [pivot for pivot in lows if pivot["known_at"] < before]
    if len(known_highs) < 2 or len(known_lows) < 2 or not _positive(atrs[before - 1]):
        return None
    buffer = atrs[before - 1] * BREAKOUT_ATR_BUFFER
    if (
        known_highs[-1]["value"] <= known_highs[-2]["value"] + buffer
        or known_lows[-1]["value"] <= known_lows[-2]["value"] + buffer
    ):
        return None
    support = known_lows[-1]
    tolerance = atrs[before - 1] * RETEST_ATR_TOLERANCE
    if bars[before - 1]["close"] <= support["value"] or any(
        bar["low"] < support["value"] - tolerance
        for bar in bars[support["index"] + 1:before]
    ):
        return None
    return {"level": support["value"]}


def _pivots(bars, field):
    result = []
    for index in range(PIVOT_WING, len(bars) - PIVOT_WING):
        value = bars[index][field]
        neighbours = [
            bars[other][field]
            for other in range(index - PIVOT_WING, index + PIVOT_WING + 1)
            if other != index
        ]
        if all(value > other if field == "high" else value < other for other in neighbours):
            result.append({"index": index, "known_at": index + PIVOT_WING, "value": value})
    return result


def _atr_series(bars):
    true_ranges = [None]
    for previous, bar in zip(bars, bars[1:]):
        true_ranges.append(max(
            bar["high"] - bar["low"],
            abs(bar["high"] - previous["close"]),
            abs(bar["low"] - previous["close"]),
        ))
    return [
        sum(true_ranges[index - ATR_PERIOD + 1:index + 1]) / ATR_PERIOD
        if index >= ATR_PERIOD else None
        for index in range(len(bars))
    ]


def _validated_bars(candles, timeframe, now):
    if not isinstance(candles, (list, tuple)):
        return [], "INVALID_CANDLE_HISTORY"
    bars = []
    symbol = None
    duration = TIMEFRAME_SECONDS[timeframe]
    for item in candles:
        if not isinstance(item, Mapping):
            return [], "INVALID_CANDLE"
        if item.get("is_final") is False:
            continue
        if item.get("is_final") is not True:
            return [], "UNCONFIRMED_CANDLE_FINALITY"
        if item.get("timeframe") != timeframe:
            return [], "MIXED_TIMEFRAME_HISTORY"
        item_symbol = item.get("symbol")
        if not isinstance(item_symbol, str) or not item_symbol.strip():
            return [], "MISSING_SYMBOL"
        item_symbol = item_symbol.strip().upper()
        if symbol is not None and item_symbol != symbol:
            return [], "MIXED_SYMBOL_HISTORY"
        symbol = item_symbol
        opened = _timestamp(item.get("open_time"))
        closed = _timestamp(item.get("close_time"))
        if opened is None or closed is None or closed <= opened:
            return [], "INVALID_CANDLE_TIMESTAMP"
        # A close can be exclusive or the final millisecond/second of a bar.
        if not duration - 1 <= (closed - opened).total_seconds() <= duration:
            return [], "INVALID_CANDLE_DURATION"
        if closed > now:
            return [], "FUTURE_FINAL_CANDLE"
        if bars:
            if abs((opened - bars[-1]["opened"]).total_seconds() - duration) > 0.001:
                return [], "NONCONTIGUOUS_CANDLE_HISTORY"
            if opened < bars[-1]["closed"]:
                return [], "OVERLAPPING_CANDLE_HISTORY"
        prices = {field: _number(item.get(field)) for field in ("open", "high", "low", "close")}
        if any(not _positive(value) for value in prices.values()):
            return [], "INVALID_OHLC"
        if prices["low"] > min(prices["open"], prices["close"]) or prices["high"] < max(prices["open"], prices["close"]):
            return [], "INVALID_OHLC"
        bars.append({**prices, "symbol": symbol, "opened": opened,
                     "closed": closed, "closed_at": closed.isoformat()})
    return bars, None


def _timestamp(value):
    try:
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        elif isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value):
            parsed = datetime.fromtimestamp(value / 1000 if abs(value) >= 100_000_000_000 else value, timezone.utc)
        else:
            return None
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def _number(value):
    try:
        return None if isinstance(value, bool) else float(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _positive(value):
    return value is not None and isfinite(value) and value > 0


def _no_setup(reason):
    return {"confirmed": False, "setup_type": "NONE", "reason": reason,
            "level": None, "invalidation_level": None, "confirmed_at": None}


def _setup(kind, level, invalidation, closed_at, sign, reason):
    if not _positive(sign * level) or not _positive(sign * invalidation):
        return _no_setup("INVALID_STRUCTURE_LEVEL")
    return {"confirmed": True, "setup_type": kind, "reason": reason,
            "level": sign * level, "invalidation_level": sign * invalidation,
            "confirmed_at": closed_at}


def _unavailable(result, reason):
    result.update(long=_no_setup(reason), short=_no_setup(reason))
    return result
