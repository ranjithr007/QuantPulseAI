from datetime import datetime, timezone

from scripts.check_directional_risk_holdout_readiness import assess_readiness
from scripts.check_directional_risk_holdout_readiness import REQUIRED_FINAL_CANDLES
from scripts.check_directional_risk_holdout_readiness import SYMBOLS


def _rows(*, short_by=0):
    return [
        {
            "symbol": symbol,
            "timeframe": timeframe,
            "final_candles": max(0, required - short_by),
            "first_close_time": datetime(2026, 8, 11, 12, tzinfo=timezone.utc),
            "latest_close_time": datetime(2026, 12, 9, 8, tzinfo=timezone.utc),
        }
        for symbol in SYMBOLS
        for timeframe, required in REQUIRED_FINAL_CANDLES.items()
    ]


def test_holdout_readiness_uses_only_complete_candle_inventory():
    result = assess_readiness(
        _rows(),
        observed_at=datetime(2026, 12, 10, tzinfo=timezone.utc),
    )

    assert result["status"] == "READY_TO_OPEN"
    assert result["outcome_data_accessed"] is False
    assert result["ready_scopes"] == 24
    assert all(scope["coverage_percent"] == 100 for scope in result["scopes"])


def test_holdout_remains_sealed_when_any_required_scope_is_short():
    rows = _rows()
    rows[0]["final_candles"] -= 1

    result = assess_readiness(rows)

    assert result["status"] == "COLLECTING_DATA"
    assert result["ready_scopes"] == 23
    assert result["scopes"][0]["missing_final_candles"] == 1


def test_missing_inventory_row_is_treated_as_zero_coverage():
    result = assess_readiness(_rows()[1:])

    assert result["status"] == "COLLECTING_DATA"
    assert result["scopes"][0]["available_final_candles"] == 0
    assert result["scopes"][0]["coverage_percent"] == 0

