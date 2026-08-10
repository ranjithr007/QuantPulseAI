"""Run the R5 DOGEUSDT baseline/adverse pair from one frozen input snapshot."""

import argparse
import json
from datetime import datetime
from pathlib import Path

from app.backtesting.frozen_replay_runner import capture_frozen_replay_context
from app.backtesting.frozen_replay_runner import load_frozen_replay_context
from app.backtesting.frozen_replay_runner import run_frozen_walk_forward
from app.backtesting.strategy_family_research import build_r5_strategy_evidence


DEFAULT_AS_OF = "2026-07-27T12:00:00+00:00"
DEFAULT_LIMIT = 12_960


def run_pair(*, input_path, output_path, as_of=DEFAULT_AS_OF):
    if Path(input_path).exists():
        context, input_payload = load_frozen_replay_context(input_path)
    else:
        context, input_payload = capture_frozen_replay_context(
            "DOGEUSDT",
            "1h",
            limit=DEFAULT_LIMIT,
            as_of_timestamp=as_of,
            output_path=input_path,
        )

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
        "strategy": "SIGNAL_GATED",
        "as_of_timestamp": datetime.fromisoformat(input_payload["as_of"]),
    }
    baseline = run_frozen_walk_forward(
        context,
        symbol="DOGEUSDT",
        timeframe="1h",
        signal="SHORT",
        **common,
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
        **common,
        fee_bps=8,
        slippage_bps=4,
        frozen_fold_parameters=frozen_parameters,
    )
    evidence = build_r5_strategy_evidence(
        baseline,
        adverse_cost_result=adverse,
    )
    payload = {
        "contract": "r5_frozen_pair_run_v1",
        "input": input_payload,
        "baseline": baseline,
        "adverse_cost": adverse,
        "evidence": evidence,
    }
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="outputs/r5_frozen_inputs/DOGEUSDT_1h_20260727T120000Z.json")
    parser.add_argument("--output", default="outputs/r5_frozen_runs/DOGEUSDT_1h_r5_pair_20260727.json")
    parser.add_argument("--as-of", default=DEFAULT_AS_OF)
    args = parser.parse_args()
    result = run_pair(input_path=args.input, output_path=args.output, as_of=args.as_of)
    print(json.dumps(result["evidence"], indent=2, default=str))
