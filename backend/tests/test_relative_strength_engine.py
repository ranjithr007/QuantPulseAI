from app.intelligence.relative_strength_engine import classify_rotation
from app.intelligence.relative_strength_engine import rank_relative_strength


TIMEFRAMES = ("1h", "2h", "4h", "1d")


def _row(symbol, returns):
    return {
        "symbol": symbol,
        "timeframe_performance": {
            timeframe: {"return_pct": value, "sample_size": 21}
            for timeframe, value in zip(TIMEFRAMES, returns)
        },
    }


def test_relative_strength_ranks_price_returns_not_signal_scores():
    rows = [
        {**_row("AAAUSDT", (3, 4, 5, 6)), "entry_score": -80},
        {**_row("BBBUSDT", (1, 2, 3, 4)), "entry_score": 99},
        {**_row("CCCUSDT", (-2, -1, 0, 1)), "entry_score": 50},
    ]

    ranked = rank_relative_strength(rows)
    by_symbol = {row["symbol"]: row["relative_strength"] for row in ranked}

    assert by_symbol["AAAUSDT"]["rank"] == 1
    assert by_symbol["AAAUSDT"]["score"] == 100.0
    assert by_symbol["BBBUSDT"]["rank"] == 2
    assert by_symbol["BBBUSDT"]["score"] == 0.0
    assert by_symbol["CCCUSDT"]["rank"] == 3
    assert by_symbol["CCCUSDT"]["score"] == -100.0
    assert by_symbol["AAAUSDT"]["execution_eligible"] is False


def test_higher_timeframes_have_more_weight_in_composite_rs():
    rows = [
        _row("FASTUSDT", (10, 10, -1, -1)),
        _row("SLOWUSDT", (-1, -1, 10, 10)),
    ]

    ranked = rank_relative_strength(rows)
    by_symbol = {row["symbol"]: row["relative_strength"] for row in ranked}

    assert by_symbol["SLOWUSDT"]["score"] > by_symbol["FASTUSDT"]["score"]
    assert by_symbol["SLOWUSDT"]["rank"] == 1


def test_equal_returns_receive_equal_percentile_scores():
    rows = [
        _row("AAAUSDT", (1, 1, 1, 1)),
        _row("BBBUSDT", (1, 1, 1, 1)),
    ]

    ranked = rank_relative_strength(rows)

    assert all(row["relative_strength"]["score"] == 0.0 for row in ranked)


def test_incomplete_history_fails_closed_for_that_symbol():
    incomplete = _row("AAAUSDT", (1, 2, 3, None))
    rows = [
        incomplete,
        _row("BBBUSDT", (1, 2, 3, 4)),
        _row("CCCUSDT", (2, 3, 4, 5)),
    ]

    ranked = rank_relative_strength(rows)
    result = next(row for row in ranked if row["symbol"] == "AAAUSDT")

    assert result["relative_strength"]["status"] == "UNAVAILABLE"
    assert result["relative_strength"]["score"] is None
    assert result["relative_strength"]["affected_timeframes"] == ["1d"]


def test_single_symbol_is_not_presented_as_relative_strength():
    ranked = rank_relative_strength([_row("AAAUSDT", (1, 2, 3, 4))])

    assert ranked[0]["relative_strength"]["status"] == "UNAVAILABLE"
    assert "At least two symbols" in ranked[0]["relative_strength"]["reason"]


def test_rotation_uses_rs_level_and_lower_vs_higher_timeframe_momentum():
    def result(score, low, high):
        return classify_rotation(
            {
                "status": "READY",
                "score": score,
                "timeframes": {
                    "1h": {"percentile_score": low},
                    "2h": {"percentile_score": low},
                    "4h": {"percentile_score": high},
                    "1d": {"percentile_score": high},
                },
            }
        )

    assert result(50, 80, 20)["quadrant"] == "LEADING"
    assert result(-50, 80, 20)["quadrant"] == "IMPROVING"
    assert result(50, 20, 80)["quadrant"] == "WEAKENING"
    assert result(-50, 20, 80)["quadrant"] == "LAGGING"


def test_rotation_is_unavailable_when_relative_strength_is_unavailable():
    result = classify_rotation({"status": "UNAVAILABLE", "reason": "stale"})

    assert result["status"] == "UNAVAILABLE"
    assert result["quadrant"] == "UNAVAILABLE"
    assert result["execution_eligible"] is False
