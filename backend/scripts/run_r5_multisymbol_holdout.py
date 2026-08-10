"""Run the R5 SHORT research profile on untouched symbol holdouts."""

import argparse
import json
from datetime import datetime
from pathlib import Path

from app.backtesting.frozen_replay_runner import load_frozen_replay_context
from app.backtesting.frozen_replay_runner import run_frozen_walk_forward
from app.backtesting.portfolio_replay import build_portfolio_replay
from app.backtesting.strategy_family_research import build_r5_strategy_evidence


DEFAULT_SYMBOLS = ("BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT", "BNBUSDT")
STRATEGY = "RESEARCH_CALIBRATION"
DOGE_CALIBRATION_FOLD_PARAMETERS = (
    {"stop_percent": 1.25, "target_percent": 2.5},
    {"stop_percent": 1.25, "target_percent": 2.0},
    {"stop_percent": 1.25, "target_percent": 2.0},
    {"stop_percent": 1.25, "target_percent": 2.0},
    {"stop_percent": 1.25, "target_percent": 2.0},
    {"stop_percent": 1.25, "target_percent": 2.0},
)


def run_holdout(
    *, symbols, input_dir, output_path, as_of, checkpoint_dir=None, window_candles=5760
):
    input_root = Path(input_dir)
    checkpoint_root = Path(checkpoint_dir) if checkpoint_dir else None
    common = {
        "limit": 12_960,
        "stop_grid": (0.75, 1.0, 1.25, 1.5),
        "target_grid": (1.5, 2.0, 2.5, 3.0),
        "train_size": 4320,
        "test_size": 1440,
        "step_size": 1440,
        "mode": "EXPANDING",
        "min_train_trades": 1,
        "initial_capital": 10_000,
        "position_size_percent": 100,
        "strategy": STRATEGY,
        "as_of_timestamp": as_of,
    }
    if int(window_candles) < common["train_size"] + common["test_size"]:
        raise ValueError("window_candles must cover one complete train and test window")
    results = {}
    baseline_symbol_results = {}
    adverse_symbol_results = {}

    for symbol in symbols:
        checkpoint_path = (
            checkpoint_root
            / f"{symbol}_1h_{as_of.strftime('%Y%m%dT%H%M%SZ')}_{STRATEGY}.json"
            if checkpoint_root
            else None
        )
        symbol_result = _load_symbol_checkpoint(
            checkpoint_path,
            symbol=symbol,
            as_of=as_of,
            window_candles=window_candles,
        )
        if symbol_result is None:
            symbol_result = _run_symbol(
                symbol=symbol,
                input_root=input_root,
                as_of=as_of,
                common=common,
                window_candles=window_candles,
            )
            _write_symbol_checkpoint(
                checkpoint_path,
                symbol=symbol,
                as_of=as_of,
                window_candles=window_candles,
                result=symbol_result,
            )
        results[symbol] = symbol_result
        baseline = symbol_result["baseline"]
        adverse = symbol_result["adverse_cost"]
        baseline_symbol_results[symbol] = baseline["out_of_sample"]
        adverse_symbol_results[symbol] = adverse["out_of_sample"]

    portfolio_options = {
        "initial_capital": 10_000,
        "max_open_positions": len(symbols),
        "max_gross_exposure_percent": len(symbols) * 100,
        "max_cluster_exposure_percent": 100,
    }
    baseline_portfolio = build_portfolio_replay(
        baseline_symbol_results,
        **portfolio_options,
    )
    adverse_portfolio = build_portfolio_replay(
        adverse_symbol_results,
        **portfolio_options,
    )
    holdout_gates = _holdout_gates(results, baseline_portfolio, adverse_portfolio)
    payload = {
        "contract": "r5_multisymbol_symbol_holdout_v1",
        "status": (
            "PASS_RESEARCH_HOLDOUT"
            if all(gate["status"] == "PASS" for gate in holdout_gates)
            else "FAIL_RESEARCH_HOLDOUT"
        ),
        "production_eligible": False,
        "holdout_type": "UNTOUCHED_SYMBOLS_NOT_TEMPORAL_HOLDOUT",
        "calibration_symbol_excluded": "DOGEUSDT",
        "symbols": list(symbols),
        "timeframe": "1h",
        "signal": "SHORT",
        "strategy": STRATEGY,
        "as_of": as_of.isoformat(),
        "window_candles": int(window_candles),
        "validation_scope": "SINGLE_SHARED_UNTOUCHED_OOS_WINDOW",
        "policy": {
            "parameter_tuning_from_this_report": "PROHIBITED",
            "parameter_selection": "FROZEN_FROM_DOGEUSDT_CALIBRATION_FOLDS",
            "frozen_fold_parameters": DOGE_CALIBRATION_FOLD_PARAMETERS,
            "promotion_requires_later_temporal_holdout": True,
            "baseline_costs": {"fee_bps": 4, "slippage_bps": 2},
            "adverse_costs": {"fee_bps": 8, "slippage_bps": 4},
        },
        "gates": holdout_gates,
        "portfolio_baseline": baseline_portfolio,
        "portfolio_adverse_cost": adverse_portfolio,
        "symbol_results": results,
    }
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return payload


def _run_symbol(*, symbol, input_root, as_of, common, window_candles):
    input_path = input_root / f"{symbol}_1h_{as_of.strftime('%Y%m%dT%H%M%SZ')}.json"
    context, input_payload = load_frozen_replay_context(input_path)
    context["candles"] = context["candles"][-int(window_candles) :]
    frozen_parameters = DOGE_CALIBRATION_FOLD_PARAMETERS[:1]
    baseline = run_frozen_walk_forward(
        context,
        symbol=symbol,
        timeframe="1h",
        signal="SHORT",
        **common,
        fee_bps=4,
        slippage_bps=2,
        frozen_fold_parameters=frozen_parameters,
    )
    adverse = run_frozen_walk_forward(
        context,
        symbol=symbol,
        timeframe="1h",
        signal="SHORT",
        **common,
        fee_bps=8,
        slippage_bps=4,
        frozen_fold_parameters=frozen_parameters,
    )
    return {
        "input": input_payload,
        "baseline": baseline,
        "adverse_cost": adverse,
        "evidence": build_r5_strategy_evidence(
            baseline,
            adverse_cost_result=adverse,
        ),
    }


def _load_symbol_checkpoint(path, *, symbol, as_of, window_candles):
    if path is None or not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        payload.get("contract") != "r5_symbol_holdout_checkpoint_v1"
        or payload.get("symbol") != symbol
        or payload.get("strategy") != STRATEGY
        or payload.get("as_of") != as_of.isoformat()
        or payload.get("window_candles") != int(window_candles)
    ):
        return None
    return payload.get("result")


def _write_symbol_checkpoint(path, *, symbol, as_of, window_candles, result):
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "contract": "r5_symbol_holdout_checkpoint_v1",
        "symbol": symbol,
        "timeframe": "1h",
        "signal": "SHORT",
        "strategy": STRATEGY,
        "as_of": as_of.isoformat(),
        "window_candles": int(window_candles),
        "result": result,
    }
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _holdout_gates(results, baseline, adverse):
    positive_symbols = sum(
        float(value["baseline"]["out_of_sample"].get("expectancy_percent") or 0) > 0
        for value in results.values()
    )
    positive_profit = {}
    for symbol, value in results.items():
        trades = value["baseline"]["out_of_sample"].get("trades") or []
        positive_profit[symbol] = sum(max(0.0, float(trade.get("pnl") or 0)) for trade in trades)
    total_positive = sum(positive_profit.values())
    concentration = (
        max(positive_profit.values(), default=0) / total_positive * 100
        if total_positive
        else None
    )
    values = {
        "portfolio_profit_factor": (
            baseline.get("profit_factor"), 1.30, lambda actual, limit: actual >= limit
        ),
        "portfolio_positive_expectancy": (
            baseline.get("expectancy_percent"), 0.0, lambda actual, limit: actual > limit
        ),
        "portfolio_max_drawdown": (
            baseline.get("max_drawdown_percent"), 20.0, lambda actual, limit: actual <= limit
        ),
        "minimum_portfolio_trades": (
            baseline.get("total_trades"), 150, lambda actual, limit: actual >= limit
        ),
        "minimum_positive_symbols": (
            positive_symbols, 3, lambda actual, limit: actual >= limit
        ),
        "maximum_symbol_profit_concentration": (
            concentration, 40.0, lambda actual, limit: actual <= limit
        ),
        "positive_under_adverse_costs": (
            adverse.get("expectancy_percent"), 0.0, lambda actual, limit: actual > limit
        ),
    }
    return [
        {
            "name": name,
            "status": (
                "INSUFFICIENT_EVIDENCE"
                if actual is None
                else "PASS" if check(float(actual), float(threshold)) else "FAIL"
            ),
            "actual": round(float(actual), 4) if actual is not None else None,
            "threshold": threshold,
        }
        for name, (actual, threshold, check) in values.items()
    ]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", default="2026-07-27T15:00:00Z")
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS)
    parser.add_argument("--input-dir", default="outputs/r5_frozen_inputs")
    parser.add_argument(
        "--checkpoint-dir",
        default="outputs/r5_frozen_runs/multisymbol_checkpoints_20260727T150000Z",
    )
    parser.add_argument("--window-candles", type=int, default=5760)
    parser.add_argument(
        "--output",
        default="outputs/r5_frozen_runs/multisymbol_short_holdout_20260727T150000Z.json",
    )
    args = parser.parse_args()
    result = run_holdout(
        symbols=tuple(args.symbols),
        input_dir=args.input_dir,
        output_path=args.output,
        as_of=datetime.fromisoformat(args.as_of.replace("Z", "+00:00")),
        checkpoint_dir=args.checkpoint_dir,
        window_candles=args.window_candles,
    )
    print(json.dumps({"status": result["status"], "gates": result["gates"]}, indent=2))
