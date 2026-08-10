import json
from datetime import datetime, timedelta, timezone

from scripts.run_r5_temporal_candidate_comparison import INSPECTED_CUTOFF
from scripts.run_r5_temporal_candidate_comparison import WINDOW_CANDLES
from scripts.run_r5_temporal_candidate_comparison import _comparison_delta
from scripts.run_r5_temporal_candidate_comparison import assess_temporal_readiness


def _write_input(path, *, symbol, as_of, test_start):
    candles = [
        {"candle_time": (test_start - timedelta(hours=4320) + timedelta(hours=i)).isoformat()}
        for i in range(WINDOW_CANDLES)
    ]
    path.write_text(
        json.dumps(
            {
                "contract": "r5_frozen_replay_input_v1",
                "symbol": symbol,
                "timeframe": "1h",
                "as_of": as_of.isoformat(),
                "candles": candles,
            }
        ),
        encoding="utf-8",
    )


def test_readiness_rejects_reused_inspected_cutoff(tmp_path):
    symbol = "BTCUSDT"
    as_of = INSPECTED_CUTOFF
    path = tmp_path / f"{symbol}_1h_{as_of.strftime('%Y%m%dT%H%M%SZ')}.json"
    _write_input(
        path,
        symbol=symbol,
        as_of=as_of,
        test_start=INSPECTED_CUTOFF - timedelta(days=10),
    )

    result = assess_temporal_readiness(
        input_dir=tmp_path,
        as_of=as_of,
        symbols=(symbol,),
    )

    assert result["status"] == "BLOCKED"
    assert "CUTOFF_NOT_LATER_THAN_INSPECTED_WINDOW" in result["reasons"]
    assert "TEST_WINDOW_OVERLAPS_INSPECTED_HISTORY" in result["symbol_checks"][symbol]["reasons"]


def test_readiness_requires_entire_test_window_after_inspected_cutoff(tmp_path):
    symbol = "BTCUSDT"
    as_of = INSPECTED_CUTOFF + timedelta(days=70)
    path = tmp_path / f"{symbol}_1h_{as_of.strftime('%Y%m%dT%H%M%SZ')}.json"
    _write_input(
        path,
        symbol=symbol,
        as_of=as_of,
        test_start=INSPECTED_CUTOFF + timedelta(hours=1),
    )

    result = assess_temporal_readiness(
        input_dir=tmp_path,
        as_of=as_of,
        symbols=(symbol,),
    )

    assert result["status"] == "READY"
    assert result["symbol_checks"][symbol]["status"] == "READY"


def test_comparison_delta_is_measured_against_control():
    control = {
        "portfolio_baseline": {
            "total_trades": 100,
            "profit_factor": 1.2,
            "expectancy_percent": 0.1,
            "max_drawdown_percent": 10,
        },
        "portfolio_adverse_cost": {"expectancy_percent": 0.02},
    }
    candidate = {
        "portfolio_baseline": {
            "total_trades": 90,
            "profit_factor": 1.4,
            "expectancy_percent": 0.2,
            "max_drawdown_percent": 8,
        },
        "portfolio_adverse_cost": {"expectancy_percent": 0.05},
    }

    delta = _comparison_delta(candidate, control)

    assert delta == {
        "total_trades": -10,
        "profit_factor": 0.2,
        "expectancy_percent": 0.1,
        "max_drawdown_percent": -2.0,
        "adverse_expectancy_percent": 0.03,
    }
