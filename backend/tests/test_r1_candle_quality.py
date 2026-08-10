from types import SimpleNamespace

from app.market_data.quality import analyze_candle_sequence
from app.market_data.quality import assess_window_coverage
from app.market_data.quality import compare_candle_sources


HOUR = 3_600_000


def test_sequence_quality_detects_gap_duplicate_and_ordering_faults():
    candles = [
        _candle(0),
        _candle(HOUR * 2),
        _candle(HOUR * 2),
        _candle(HOUR),
    ]

    result = analyze_candle_sequence(candles, "1h")

    assert result["status"] == "FAIL"
    assert result["duplicate_open_times"] == [HOUR * 2]
    assert result["missing_candle_count"] == 0
    assert result["out_of_order"]
    assert "DUPLICATE_OPEN_TIMES" in result["issues"]
    assert "OUT_OF_ORDER" in result["issues"]


def test_sequence_quality_reports_missing_boundaries():
    result = analyze_candle_sequence(
        [_candle(0), _candle(HOUR * 3)],
        "1h",
    )

    assert result["missing_candle_count"] == 2
    assert result["gaps"][0]["first_missing_open_time_ms"] == HOUR
    assert result["gaps"][0]["last_missing_open_time_ms"] == HOUR * 2


def test_source_comparison_separates_price_and_volume_disagreement():
    primary = [_candle(0, close=100.0, volume=1000.0)]
    secondary = [_candle(0, close=100.1, volume=100.0)]

    result = compare_candle_sources(
        primary,
        secondary,
        price_tolerance_bps=25,
        volume_tolerance_ratio=0.5,
    )

    assert result["overlap_count"] == 1
    assert result["disagreement_count"] == 1
    assert result["status"] == "PASS"
    assert result["price_disagreement_count"] == 0
    assert result["volume_context_difference_count"] == 1
    assert result["disagreements"][0]["price_mismatch"] is False
    assert result["disagreements"][0]["volume_mismatch"] is True


def test_window_coverage_counts_leading_and_internal_missing_candles():
    result = assess_window_coverage(
        [_candle(HOUR), _candle(HOUR * 3)],
        "1h",
        start_time_ms=0,
        end_time_ms=HOUR * 5,
    )

    assert result["expected_count"] == 5
    assert result["observed_count"] == 2
    assert result["missing_count"] == 3
    assert result["missing_open_time_sample"] == [
        0,
        HOUR * 2,
        HOUR * 4,
    ]


def test_source_comparison_refuses_pass_without_overlap():
    result = compare_candle_sources([_candle(0)], [])

    assert result["status"] == "INSUFFICIENT_OVERLAP"
    assert result["overlap_count"] == 0


def _candle(open_time_ms, *, close=100.0, volume=1000.0):
    return SimpleNamespace(
        open_time_ms=open_time_ms,
        is_final=True,
        open_price=100.0,
        high_price=101.0,
        low_price=99.0,
        close_price=close,
        volume=volume,
    )
