"""Compare research-only R5 gate challengers on one frozen replay input."""

import argparse
import json
from datetime import datetime
from pathlib import Path

from app.backtesting.frozen_replay_runner import load_frozen_replay_context
from app.backtesting.frozen_replay_runner import run_frozen_walk_forward
from app.backtesting.strategy_family_research import build_r5_strategy_evidence


STRATEGIES = ("RESEARCH_CALIBRATION", "SHORT_EDGE_CALIBRATION")


def run_comparison(*, input_path, output_path):
    context, input_payload = load_frozen_replay_context(input_path)
    common = {
        "limit": int(input_payload["limit"]),
        "stop_grid": (0.75, 1.0, 1.25, 1.5),
        "target_grid": (1.5, 2.0, 2.5, 3.0),
        "train_size": 4320,
        "test_size": 1440,
        "step_size": 1440,
        "mode": "EXPANDING",
        "min_train_trades": 1,
        "initial_capital": 10_000,
        "position_size_percent": 100,
        "strategy": "RESEARCH_CALIBRATION",
        "as_of_timestamp": datetime.fromisoformat(input_payload["as_of"]),
    }

    results = {}
    for strategy in STRATEGIES:
        baseline = run_frozen_walk_forward(
            context,
            symbol="DOGEUSDT",
            timeframe="1h",
            signal="SHORT",
            **{**common, "strategy": strategy},
            fee_bps=4,
            slippage_bps=2,
        )
        frozen_parameters = [
            dict(fold.get("selected_parameters") or {})
            for fold in baseline.get("folds") or []
        ]
        adverse = run_frozen_walk_forward(
            context,
            symbol="DOGEUSDT",
            timeframe="1h",
            signal="SHORT",
            **{**common, "strategy": strategy},
            fee_bps=8,
            slippage_bps=4,
            frozen_fold_parameters=frozen_parameters,
        )
        results[strategy] = {
            "baseline": baseline,
            "adverse_cost": adverse,
            "evidence": build_r5_strategy_evidence(
                baseline,
                adverse_cost_result=adverse,
            ),
        }

    payload = {
        "contract": "r5_frozen_challenger_comparison_v1",
        "input": input_payload,
        "official_baseline_artifact": (
            "outputs/r5_frozen_runs/DOGEUSDT_1h_r5_pair_20260727.json"
        ),
        "comparison_policy": {
            "same_frozen_input": True,
            "same_fold_boundaries": True,
            "same_baseline_costs": True,
            "same_adverse_costs": True,
            "production_promotion": "PROHIBITED_FROM_THIS_COMPARISON_ALONE",
        },
        "strategies": results,
    }
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        default="outputs/r5_frozen_inputs/DOGEUSDT_1h_20260727T120000Z.json",
    )
    parser.add_argument(
        "--output",
        default="outputs/r5_frozen_runs/DOGEUSDT_1h_r5_challengers_20260728.json",
    )
    args = parser.parse_args()
    result = run_comparison(input_path=args.input, output_path=args.output)
    print(
        json.dumps(
            {
                strategy: value["evidence"]
                for strategy, value in result["strategies"].items()
            },
            indent=2,
            default=str,
        )
    )
