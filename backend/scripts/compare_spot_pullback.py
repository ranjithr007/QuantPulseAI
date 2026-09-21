"""Execute the finite comparison plan, retaining every trial and provenance."""
import argparse
from dataclasses import replace
import gzip
from hashlib import sha256
import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.backtesting.spot_pullback_research import ResearchConfig, run_screen
from app.backtesting.spot_pullback_comparison import buy_hold, diagnostics, validate_policy
from run_spot_pullback_research import load_inputs


def dump(path, value):
    with path.open("x", encoding="utf-8") as output:
        json.dump(value, output, indent=2, allow_nan=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    plan_path = ROOT / "docs/spot-pullback-comparison-plan.json"
    plan_bytes = plan_path.read_bytes()
    plan = json.loads(plan_bytes)
    for policy in plan["candidates"]:
        validate_policy(policy)
    args.output.mkdir(parents=True, exist_ok=False)
    candles, hashes = load_inputs(args.directory)
    window = plan["data"]
    candles = {s: f.loc[(f.index >= pd.Timestamp(window["history_start"])) &
                       (f.index < pd.Timestamp(window["end"]))] for s, f in candles.items()}
    source_paths = [Path(__file__), ROOT / "app/backtesting/spot_pullback_research.py",
                    ROOT / "app/backtesting/spot_pullback_comparison.py",
                    ROOT / "scripts/run_spot_pullback_research.py"]
    sources = {str(p.relative_to(ROOT)): sha256(p.read_bytes()).hexdigest() for p in source_paths}
    # Written before the first trial. This is a local ledger, not an external
    # time-stamped registration service or a guarantee against manual tampering.
    manifest = {"recorded_before_trials_at": pd.Timestamp.now(tz="UTC").isoformat(),
                "plan": plan, "plan_sha256": sha256(plan_bytes).hexdigest(),
                "source_sha256": sources, "dataset_sha256": hashes,
                "fee_tier": "Regular-user published assumption; user authorized Binance data, tier not confirmed",
                "promotion_allowed": False}
    dump(args.output / "registration.json", manifest)
    config = ResearchConfig()
    runs = [(p, "baseline", config) for p in plan["candidates"]]
    fixed = next(p for p in plan["candidates"] if p["id"] == plan["fixed_stress_candidate"])
    runs.extend([(fixed, "double_execution_cost", replace(config, execution_bps=10)),
                 (fixed, "delay_15_minutes", replace(config, entry_delay_bars=1))])
    results = []
    for policy, scenario, settings in runs:
        name = policy["id"] + "_" + scenario
        print(f"Running {name}", flush=True)
        result = run_screen(candles, start=window["start"], end=window["end"], config=settings, policy=policy)
        result["diagnostics"] = diagnostics(result)
        curve = result.pop("equity_curve")
        with gzip.open(args.output / (name + "_equity.json.gz"), "xt", encoding="utf-8") as stream:
            json.dump(curve, stream, allow_nan=False)
        result["equity_curve_file"] = name + "_equity.json.gz"
        dump(args.output / (name + ".json"), result)
        row = {"name": name, "policy": policy, "scenario": scenario,
               "metrics": result["metrics"], "diagnostics": result["diagnostics"],
               "risk_events": result["risk_events"], "gates": result["observed_metric_gates"]}
        results.append(row)
        print(json.dumps({"name": name, **result["metrics"]}), flush=True)
    benchmarks = {"cash": {"return_percent": 0, "max_drawdown_percent": 0},
                  "buy_hold_50": buy_hold(candles, window["start"], window["end"], .5, config),
                  "buy_hold_100": buy_hold(candles, window["start"], window["end"], 1., config)}
    if sha256(plan_path.read_bytes()).hexdigest() != manifest["plan_sha256"]:
        raise RuntimeError("Plan changed during experiment")
    if any(sha256(p.read_bytes()).hexdigest() != sources[str(p.relative_to(ROOT))] for p in source_paths):
        raise RuntimeError("Research code changed during experiment")
    final = {"experiment_id": plan["experiment_id"], "runs": results, "benchmarks": benchmarks,
             "promotion_allowed": False, "status": "EXPLORATORY_COMPARISON_COMPLETE"}
    dump(args.output / "comparison.json", final)
    lines = ["# Confidential — fixed horizon/cap comparison", "",
             "Development data: BTC/ETH, January 2024–December 2025. No 2026 prices used.", "",
             "Not an untouched validation sample. Seven planned runs; no parameter search or live promotion.", "",
             "| Candidate/scenario | Trades | Win rate | Account return | Max DD | Profit factor |",
             "|---|---:|---:|---:|---:|---:|"]
    def fmt(x, percent=False):
        return "N/A" if x is None else f"{x:.3f}" + ("%" if percent else "")
    for row in results:
        m = row["metrics"]
        lines.append(f"| {row['name']} | {m['closed_trades']} | {fmt(m['net_win_rate_percent'], True)} | "
                     f"{fmt(m['return_percent'], True)} | {fmt(m['max_drawdown_percent'], True)} | {fmt(m['profit_factor'])} |")
    lines.extend(["", "## Benchmarks", "",
                  "Buy-and-hold allocations are initial allocations, not continuing exposure caps. No stop protection; risk is not matched.", ""])
    for name, m in benchmarks.items():
        lines.append(f"- {name}: return {fmt(m['return_percent'], True)}, drawdown {fmt(m['max_drawdown_percent'], True)}.")
    lines.extend(["", "## Interpretation constraints", "",
                  "Hourly policies also scale trend context to four hours and maximum holding time to 24 hours; this compares horizon packages, not entry interval alone.", "",
                  "The simple trend comparator enters only on a new bullish trend state, uses a two-ATR stop, and retains the same risk/cost limits.", "",
                  "Fees: 10 bps per side, consistent with the current published regular-user spot rate. Execution allowance: assumed 5 bps per side. Historical pair promotions, actual account tiers and actual spreads are not reconstructed.", "",
                  "Source: [Binance fee schedule](https://www.binance.com/en/fee/trading), checked 2026-09-21.", "",
                  "Costs are charged in quote-equivalent amounts; actual fee-asset inventory and lot-size effects are not simulated.", "",
                  "All variants retain the prior screen's execution, news, universe and statistical limitations. Weekly-block intervals are descriptive and not adjusted for selecting a winner. No strategy is approved by this comparison.", "",
                  "See comparison.json for yearly/asset diagnostics and each named run for trades, daily returns and stop reviews. registration.json records the plan/data/code hashes before trials."])
    (args.output / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Saved {args.output / 'summary.md'}", flush=True)


if __name__ == "__main__":
    main()
