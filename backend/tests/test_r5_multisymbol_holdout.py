from datetime import datetime, timezone

from scripts.run_r5_multisymbol_holdout import _holdout_gates
from scripts.run_r5_multisymbol_holdout import _load_symbol_checkpoint
from scripts.run_r5_multisymbol_holdout import _write_symbol_checkpoint


def _symbol_result(expectancy, pnl):
    return {
        "baseline": {
            "out_of_sample": {
                "expectancy_percent": expectancy,
                "trades": [{"pnl": pnl}],
            }
        }
    }


def test_holdout_gates_require_breadth_and_adverse_cost_survival():
    results = {
        "BTCUSDT": _symbol_result(0.20, 20),
        "ETHUSDT": _symbol_result(0.10, 20),
        "XRPUSDT": _symbol_result(0.05, 20),
        "SOLUSDT": _symbol_result(-0.05, 20),
        "BNBUSDT": _symbol_result(-0.10, 20),
    }
    baseline = {
        "profit_factor": 1.35,
        "expectancy_percent": 0.08,
        "max_drawdown_percent": 12.0,
        "total_trades": 180,
    }
    adverse = {"expectancy_percent": 0.01}

    gates = {
        gate["name"]: gate
        for gate in _holdout_gates(results, baseline, adverse)
    }

    assert all(gate["status"] == "PASS" for gate in gates.values())
    assert gates["minimum_positive_symbols"]["actual"] == 3
    assert gates["maximum_symbol_profit_concentration"]["actual"] == 20


def test_holdout_gates_fail_concentration_and_negative_adverse_expectancy():
    results = {
        "BTCUSDT": _symbol_result(0.20, 80),
        "ETHUSDT": _symbol_result(0.10, 5),
        "XRPUSDT": _symbol_result(0.05, 5),
        "SOLUSDT": _symbol_result(-0.05, 5),
        "BNBUSDT": _symbol_result(-0.10, 5),
    }
    baseline = {
        "profit_factor": 1.35,
        "expectancy_percent": 0.08,
        "max_drawdown_percent": 12.0,
        "total_trades": 180,
    }
    adverse = {"expectancy_percent": -0.01}

    gates = {
        gate["name"]: gate
        for gate in _holdout_gates(results, baseline, adverse)
    }

    assert gates["maximum_symbol_profit_concentration"]["status"] == "FAIL"
    assert gates["positive_under_adverse_costs"]["status"] == "FAIL"


def test_symbol_checkpoint_round_trip_rejects_a_different_symbol(tmp_path):
    path = tmp_path / "BTCUSDT.json"
    as_of = datetime(2026, 7, 27, 15, tzinfo=timezone.utc)
    result = {"baseline": {"out_of_sample": {"total_trades": 10}}}

    _write_symbol_checkpoint(
        path,
        symbol="BTCUSDT",
        as_of=as_of,
        window_candles=5760,
        result=result,
    )

    assert (
        _load_symbol_checkpoint(
            path, symbol="BTCUSDT", as_of=as_of, window_candles=5760
        )
        == result
    )
    assert (
        _load_symbol_checkpoint(
            path, symbol="ETHUSDT", as_of=as_of, window_candles=5760
        )
        is None
    )
