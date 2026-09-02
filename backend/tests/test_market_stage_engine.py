from app.intelligence.market_stage_engine import analyze_market_stage


def _record(timeframe, trend_score, trend, momentum_score=50):
    return {
        "timeframe": timeframe,
        "status": "OK",
        "freshness": {"status": "FRESH", "is_stale": False},
        "feature_trend": trend,
        "feature_trend_score": trend_score,
        "feature_momentum_score": momentum_score,
    }


def test_stage_two_requires_bullish_higher_and_lower_timeframes():
    result = analyze_market_stage(
        [
            _record("1h", 64, "BULLISH"),
            _record("2h", 66, "BULLISH"),
            _record("4h", 70, "BULLISH"),
            _record("1d", 72, "BULLISH"),
        ]
    )

    assert result["status"] == "READY"
    assert result["stage"] == "Stage 2 Uptrend"
    assert result["execution_eligible"] is False


def test_stage_four_requires_bearish_higher_and_lower_timeframes():
    result = analyze_market_stage(
        [
            _record("1h", 36, "BEARISH"),
            _record("2h", 34, "BEARISH"),
            _record("4h", 30, "BEARISH"),
            _record("1d", 28, "BEARISH"),
        ]
    )

    assert result["status"] == "READY"
    assert result["stage"] == "Stage 4 Downtrend"


def test_recovering_lower_timeframes_are_a_stage_one_base():
    result = analyze_market_stage(
        [
            _record("1h", 56, "SIDEWAYS"),
            _record("2h", 54, "SIDEWAYS"),
            _record("4h", 42, "BEARISH"),
            _record("1d", 40, "BEARISH"),
        ]
    )

    assert result["status"] == "READY"
    assert result["stage"] == "Stage 1 Base"
    assert result["lower_minus_higher"] == 14.0


def test_weakening_lower_timeframes_are_a_stage_three_transition():
    result = analyze_market_stage(
        [
            _record("1h", 48, "SIDEWAYS"),
            _record("2h", 50, "SIDEWAYS"),
            _record("4h", 62, "BULLISH"),
            _record("1d", 66, "BULLISH"),
        ]
    )

    assert result["status"] == "READY"
    assert result["stage"] == "Stage 3 Transition"


def test_stage_fails_closed_when_a_timeframe_is_missing():
    result = analyze_market_stage(
        [
            _record("1h", 64, "BULLISH"),
            _record("2h", 66, "BULLISH"),
            _record("4h", 70, "BULLISH"),
        ]
    )

    assert result["status"] == "MISSING"
    assert result["stage"] == "UNAVAILABLE"
    assert result["affected_timeframes"] == ["1d"]


def test_stage_fails_closed_when_any_timeframe_is_stale():
    records = [
        _record("1h", 64, "BULLISH"),
        _record("2h", 66, "BULLISH"),
        _record("4h", 70, "BULLISH"),
        _record("1d", 72, "BULLISH"),
    ]
    records[1]["freshness"] = {"status": "STALE", "is_stale": True}

    result = analyze_market_stage(records)

    assert result["status"] == "STALE"
    assert result["stage"] == "UNAVAILABLE"
    assert result["affected_timeframes"] == ["2h"]
