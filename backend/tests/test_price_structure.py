"""Deterministic offline acceptance tests for closed price-structure evidence."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest

from app.intelligence.market_participation_trend_engine import analyze_spot_timeframe
from app.strategies.price_structure import build_price_structure


NOW = datetime(2026, 8, 1, tzinfo=timezone.utc)
PERIODS = {"1h": 1, "2h": 2, "4h": 4, "1d": 24}


def _bars(closes, *, timeframe="1h"):
    period = timedelta(hours=PERIODS[timeframe])
    return [
        {
            "symbol": "BTCUSDT", "timeframe": timeframe, "is_final": True,
            "open_time": NOW - period * (len(closes) - index),
            "close_time": NOW - period * (len(closes) - index - 1),
            "open": close - 0.2, "high": close + 0.5,
            "low": close - 0.5, "close": close,
        }
        for index, close in enumerate(closes)
    ]


def _breakout(*, timeframe="1h"):
    bars = _bars([
        100, 101, 102, 101, 100, 99, 98, 99, 100, 101,
        102, 101, 100, 99, 98, 99, 100, 101, 102, 103,
        104, 103, 102, 101, 102, 103, 103.5, 104.2, 105.4, 105.1,
    ], timeframe=timeframe)
    bars[-1].update(open=105.6, high=105.8, low=104.55, close=105.1)
    return bars


def _pullback():
    return _bars([
        100, 101, 102, 101, 100, 99, 98, 99, 100, 101,
        104, 103, 101, 100, 99, 100, 102, 104, 106, 105,
        104, 103, 102, 103, 104, 104, 103, 102.3, 102, 103.1,
    ])


def _direction(bars, side):
    if side == "long":
        return deepcopy(bars)
    result = deepcopy(bars)
    for bar in result:
        bar.update(open=220 - bar["open"], close=220 - bar["close"],
                   high=220 - bar["low"], low=220 - bar["high"])
    return result


@pytest.mark.parametrize("side", ["long", "short"])
def test_real_closed_breakout_requires_and_accepts_a_later_retest(side):
    bars = _direction(_breakout(), side)
    untested = build_price_structure(bars[:-1], "1h", now=NOW)
    assert untested[side]["confirmed"] is False

    result = build_price_structure(bars, "1h", now=NOW)
    evidence = result[side]
    assert result["profile"] == "CONFIRMED_PRICE_STRUCTURE_V1"
    assert result["symbol"] == "BTCUSDT"
    assert result["status"] == "READY"
    assert result["structure"] == ("BULLISH" if side == "long" else "BEARISH")
    assert evidence["confirmed"] is True
    assert evidence["setup_type"] == "BREAKOUT_RETEST"
    assert evidence["confirmed_at"] == NOW.isoformat()
    assert evidence["level"] == pytest.approx(104.5 if side == "long" else 115.5)
    assert result["short" if side == "long" else "long"]["confirmed"] is False
    if side == "long":
        assert evidence["invalidation_level"] < evidence["level"] < result["close"]
    else:
        assert evidence["invalidation_level"] > evidence["level"] > result["close"]
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("side", ["long", "short"])
def test_intact_prior_swing_trend_pullback_does_not_need_a_new_extreme(side):
    bars = _direction(_pullback(), side)
    result = build_price_structure(bars, "1h", now=NOW)
    assert result[side]["confirmed"] is True
    assert result[side]["setup_type"] == "PULLBACK"
    assert result[side]["level"] == pytest.approx(101.5 if side == "long" else 118.5)
    # Recovery is well inside the old trend extreme; no fresh HH/LL is required.
    if side == "long":
        assert bars[-1]["high"] < bars[18]["high"]
    else:
        assert bars[-1]["low"] > bars[18]["low"]


@pytest.mark.parametrize("side", ["long", "short"])
def test_higher_lows_without_prior_higher_highs_cannot_become_a_pullback(side):
    bars = _pullback()
    bars[10]["high"] = 110
    bars[18]["high"] = 110
    result = build_price_structure(_direction(bars, side), "1h", now=NOW)
    assert result["status"] == "READY"
    assert not result["long"]["confirmed"]
    assert not result["short"]["confirmed"]


@pytest.mark.parametrize("side", ["long", "short"])
def test_future_confirmed_pivot_is_not_available_for_an_earlier_touch(side):
    bars = _bars([
        100, 101, 102, 101, 100, 99, 98, 99, 100, 101,
        104, 103, 101, 100, 99, 100, 102, 104, 106, 105,
        104.5, 104.2, 104, 104.2, 104.4, 103, 102, 102.8, 102.1, 103.2,
    ])
    # The latest HL at 26 becomes known only at the CLOSE of 28, which is
    # itself the touch. A scan after 29 must not retroactively know it at 28.
    result = build_price_structure(_direction(bars, side), "1h", now=NOW)
    assert result["status"] == "READY"
    assert result[side]["confirmed"] is False


@pytest.mark.parametrize("side", ["long", "short"])
def test_wick_only_breakout_cannot_confirm(side):
    bars = _breakout()
    bars[-2].update(open=104.0, close=104.4, low=103.9, high=105.9)
    bars[-1].update(open=104.3, close=104.4, low=104.1, high=105.8)
    result = build_price_structure(_direction(bars, side), "1h", now=NOW)
    assert result[side]["confirmed"] is False


@pytest.mark.parametrize("side", ["long", "short"])
def test_breakout_must_hold_its_invalidation_boundary(side):
    bars = _breakout()
    bars[-1]["low"] = 102.0
    result = build_price_structure(_direction(bars, side), "1h", now=NOW)
    assert result[side]["confirmed"] is False


@pytest.mark.parametrize("side", ["long", "short"])
def test_pullback_requires_later_directional_recovery(side):
    bars = _pullback()
    bars[-1].update(open=102.3, close=101.9, low=101.6, high=102.5)
    result = build_price_structure(_direction(bars, side), "1h", now=NOW)
    assert result[side]["confirmed"] is False


@pytest.mark.parametrize("side", ["long", "short"])
def test_broken_prior_higher_low_or_lower_high_cannot_confirm(side):
    bars = _pullback()
    bars[-2]["low"] = 100.0
    result = build_price_structure(_direction(bars, side), "1h", now=NOW)
    assert result[side]["confirmed"] is False


def test_old_retest_without_a_recent_trigger_is_not_reused():
    bars = _breakout()
    for index in range(4):
        bars.append({**bars[-1], "open_time": NOW + timedelta(hours=index),
                     "close_time": NOW + timedelta(hours=index + 1),
                     "open": 106 + index, "high": 107 + index,
                     "low": 105.8 + index, "close": 106.5 + index})
    result = build_price_structure(bars, "1h", now=NOW + timedelta(hours=4))
    assert result["status"] == "READY"
    assert result["long"]["confirmed"] is False


@pytest.mark.parametrize("timeframe", list(PERIODS))
def test_each_timeframe_keeps_its_actual_stale_source_time(timeframe):
    result = build_price_structure(_breakout(timeframe=timeframe), timeframe,
                                   now=NOW + timedelta(days=90))
    assert result["status"] == "READY"
    assert result["long"]["confirmed"] is True
    assert result["closed_at"] == NOW.isoformat()
    assert result["long"]["confirmed_at"] == NOW.isoformat()


def test_finality_filter_excludes_a_future_forming_bar_without_changing_evidence():
    bars = _breakout()
    expected = build_price_structure(bars, "1h", now=NOW)
    bars.append({**bars[-1], "open_time": NOW, "close_time": NOW + timedelta(hours=1),
                 "is_final": False, "high": float("nan")})
    assert build_price_structure(bars, "1h", now=NOW) == expected


def test_a_future_final_bar_is_rejected_instead_of_stamped_current():
    result = build_price_structure(_breakout(), "1h", now=NOW - timedelta(seconds=1))
    assert result["status"] == "UNAVAILABLE"
    assert result["long"]["reason"] == "FUTURE_FINAL_CANDLE"
    assert result["closed_at"] is None


@pytest.mark.parametrize("invalid", [None, [], {}, [None], _breakout()[:24]])
def test_minimal_or_malformed_input_fails_closed(invalid):
    result = build_price_structure(invalid, "1h", now=NOW)
    assert result["status"] == "UNAVAILABLE"
    assert not result["long"]["confirmed"]
    assert not result["short"]["confirmed"]
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("field,value", [
    ("high", float("nan")), ("close", float("inf")), ("low", -1),
    ("open", "bad"), ("open", True), ("low", 500), ("high", 1),
    ("timeframe", "4h"), ("symbol", "ETHUSDT"), ("symbol", None),
    ("open_time", None), ("close_time", "not-a-date"), ("is_final", None),
])
def test_invalid_candle_data_fails_closed(field, value):
    bars = _breakout()
    bars[10][field] = value
    result = build_price_structure(bars, "1h", now=NOW)
    assert result["status"] == "UNAVAILABLE"
    assert not result["long"]["confirmed"]
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("kind", ["duplicate", "gap", "reorder", "interior_forming", "duration"])
def test_broken_candle_chronology_fails_closed(kind):
    bars = _breakout()
    if kind == "duplicate":
        bars.insert(10, deepcopy(bars[10]))
    elif kind == "gap":
        bars.pop(10)
    elif kind == "reorder":
        bars[10], bars[11] = bars[11], bars[10]
    elif kind == "interior_forming":
        bars[10]["is_final"] = False
    else:
        bars[10]["close_time"] -= timedelta(minutes=10)
    result = build_price_structure(bars, "1h", now=NOW)
    assert result["status"] == "UNAVAILABLE"


def test_exchange_inclusive_closes_and_database_naive_utc_are_supported():
    bars = _breakout()
    for bar in bars:
        bar["open_time"] = bar["open_time"].replace(tzinfo=None)
        bar["close_time"] = (bar["close_time"] - timedelta(milliseconds=1)).replace(tzinfo=None)
    result = build_price_structure(bars, "1h", now=NOW)
    assert result["long"]["confirmed"] is True
    assert result["closed_at"] == (NOW - timedelta(milliseconds=1)).isoformat()


@pytest.mark.parametrize("encoding", ["iso", "seconds", "milliseconds"])
def test_timestamp_encodings_are_normalized_to_json_safe_utc(encoding):
    bars = _breakout()
    for bar in bars:
        for field in ("open_time", "close_time"):
            value = bar[field]
            bar[field] = value.isoformat() if encoding == "iso" else value.timestamp() * (1000 if encoding == "milliseconds" else 1)
    result = build_price_structure(bars, "1h", now=NOW)
    assert result["long"]["confirmed"] is True
    assert result["closed_at"] == NOW.isoformat()


def test_zero_atr_is_unavailable_and_nonzero_compression_cannot_confirm():
    flat = _bars([100] * 30)
    for bar in flat:
        bar.update(open=100, high=100, low=100, close=100)
    assert build_price_structure(flat, "1h", now=NOW)["status"] == "UNAVAILABLE"
    compressed = build_price_structure(_bars([100] * 30), "1h", now=NOW)
    assert compressed["status"] == "READY"
    assert compressed["structure"] == "COMPRESSION"
    assert not compressed["long"]["confirmed"]
    assert not compressed["short"]["confirmed"]


@pytest.mark.parametrize("side", ["long", "short"])
def test_compressed_recent_range_requires_breakout_even_with_old_swing_trend(side):
    bars = _pullback()
    bars[16]["low"] = 90
    result = build_price_structure(_direction(bars, side), "1h", now=NOW)
    assert result["status"] == "READY"
    assert result["structure"] == "COMPRESSION"
    assert result[side]["confirmed"] is False


def test_participation_attaches_structure_without_replacing_its_score_or_direction():
    bars = _breakout()
    before = deepcopy(bars)
    result = analyze_spot_timeframe("BTCUSDT", "1h", bars)
    assert result["status"] == "READY"
    assert result["score"] == result["score_components"]["total"]
    assert result["price_structure"]["profile"] == "CONFIRMED_PRICE_STRUCTURE_V1"
    assert result["price_structure"]["long"]["confirmed"] is True
    assert bars == before


def test_participation_symbol_mismatch_cannot_attach_usable_structure():
    result = analyze_spot_timeframe("ETHUSDT", "1h", _breakout())
    assert result["status"] == "READY"
    assert result["price_structure"]["status"] == "UNAVAILABLE"
    assert result["price_structure"]["long"]["reason"] == "SYMBOL_MISMATCH"
    assert not result["price_structure"]["long"]["confirmed"]
