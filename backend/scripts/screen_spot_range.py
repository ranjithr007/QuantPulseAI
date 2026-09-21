"""One fixed range-reversion development screen; no fresh validation data."""
from dataclasses import asdict, replace
import argparse
import gzip
from hashlib import sha256
import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.backtesting.spot_pullback_research import ResearchConfig, run_screen
from app.backtesting.spot_pullback_comparison import buy_hold, diagnostics
from app.backtesting.spot_range_reversion import VERSION
from run_spot_pullback_research import load_inputs


def dump(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--previous-comparison", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    config = ResearchConfig()
    scenarios = [("baseline", config), ("double_execution_cost", replace(config, execution_bps=10)),
                 ("delay_15_minutes", replace(config, entry_delay_bars=1))]
    specification = ROOT / "docs/spot-range-reversion-hypothesis-v1.md"
    sources = [Path(__file__), ROOT / "app/backtesting/spot_range_reversion.py",
               ROOT / "app/backtesting/spot_pullback_research.py",
               ROOT / "app/backtesting/spot_pullback_comparison.py",
               ROOT / "scripts/run_spot_pullback_research.py", specification]
    hashes = {str(p.relative_to(ROOT)): sha256(p.read_bytes()).hexdigest() for p in sources}
    start, end = "2024-01-01T00:00:00Z", "2026-01-01T00:00:00Z"
    dump(args.output / "registration.json", {
        "created_before_trials_at": pd.Timestamp.now(tz="UTC").isoformat(), "version": VERSION,
        "start": start, "end_exclusive": end, "warmup_start": "2023-04-01T00:00:00Z",
        "source_sha256": hashes, "scenarios": {k: asdict(v) for k, v in scenarios},
        "data_role": "ALREADY_CONSUMED_DEVELOPMENT_ONLY", "promotion_allowed": False,
        "interpretation": "Fixed SMA target; risk/size use conservative cost reserve; no news/book/lot evidence fabricated. First candle excluded from Wilder TR/DM seeds as specified."
    })
    frames, data_hashes = load_inputs(args.directory)
    frames = {s: f.loc[(f.index >= pd.Timestamp("2023-04-01T00:00Z")) &
                      (f.index < pd.Timestamp(end))] for s, f in frames.items()}
    dump(args.output / "data_provenance.json", data_hashes)
    rows = []
    for name, settings in scenarios:
        print(f"Running {name}", flush=True)
        result = run_screen(frames, start=start, end=end, config=settings, policy={"id": VERSION})
        result["diagnostics"] = diagnostics(result)
        curve = result.pop("equity_curve")
        with gzip.open(args.output / f"{name}_equity.json.gz", "xt", encoding="utf-8") as stream:
            json.dump(curve, stream, allow_nan=False)
        result["equity_curve_file"] = f"{name}_equity.json.gz"
        dump(args.output / f"{name}.json", result)
        rows.append({"scenario": name, "metrics": result["metrics"],
                     "diagnostics": result["diagnostics"], "gates": result["observed_metric_gates"]})
        print(json.dumps({"scenario": name, **result["metrics"]}), flush=True)
    previous_path = args.previous_comparison / "comparison.json"
    previous = json.loads(previous_path.read_text())
    comparator = next(r for r in previous["runs"] if r["name"] == "B1_TREND_ONLY_baseline")
    benchmarks = {"cash": {"return_percent": 0., "max_drawdown_percent": 0.},
                  "buy_hold_initial_50": buy_hold(frames, start, end, .5, config),
                  "buy_hold_initial_100": buy_hold(frames, start, end, 1., config)}
    for path in sources:
        if sha256(path.read_bytes()).hexdigest() != hashes[str(path.relative_to(ROOT))]:
            raise ValueError("Registered code or specification changed during trial")
    for symbol, expected in data_hashes.items():
        if sha256((args.directory / f"{symbol}.csv").read_bytes()).hexdigest() != expected:
            raise ValueError("Dataset changed during trial")
    report = {"version": VERSION, "runs": rows, "benchmarks": benchmarks,
              "existing_trend_comparator": comparator["metrics"],
              "comparator_file_sha256": sha256(previous_path.read_bytes()).hexdigest(),
              "promotion_allowed": False, "data_role": "DEVELOPMENT_ONLY"}
    dump(args.output / "comparison.json", report)
    lines = ["# Confidential — fixed range-reversion development screen", "",
             "BTC/ETH, January 2024–December 2025. Reused development data; no new holdout.", "",
             "| Scenario | Trades | Win rate | Account return | Max drawdown | Profit factor |",
             "|---|---:|---:|---:|---:|---:|"]
    def fmt(x, pct=False):
        return "N/A" if x is None else f"{x:.3f}" + ("%" if pct else "")
    for row in rows:
        m = row["metrics"]
        lines.append(f"| {row['scenario']} | {m['closed_trades']} | {fmt(m['net_win_rate_percent'], True)} | "
                     f"{fmt(m['return_percent'], True)} | {fmt(m['max_drawdown_percent'], True)} | {fmt(m['profit_factor'])} |")
    lines.extend(["", "## Rejection diagnostics", ""])
    for row in rows:
        lines.append(f"- {row['scenario']}: {json.dumps(row['diagnostics']['first_failure_counts'], sort_keys=True)}")
    lines.extend(["", "## Existing comparators", "",
                  "Buy-and-hold has different risk and uncontrolled drifting exposure; it is a reference, not a recommendation.", ""])
    for name, value in benchmarks.items():
        lines.append(f"- {name}: return {fmt(value['return_percent'], True)}, drawdown {fmt(value['max_drawdown_percent'], True)}.")
    m = comparator["metrics"]
    lines.append(f"- Previously rejected simple trend: {m['closed_trades']} trades; return {fmt(m['return_percent'], True)}. Copied from the existing experiment, not a new run or new evidence.")
    lines.extend(["", "## Decision boundary", "",
                  "No promotion. No parameter tuning performed. Too few trades or nonpositive expectancy rejects this development candidate under the frozen plan. Zero trades are not evidence of profitability or safety.", "",
                  "The previous fee/slippage assumptions remain unchanged. Current two-minute book observations were not retroactively substituted into historical costs. Venue lot filters, spread/depth, news and verified fills remain unmodeled. All prior paper/live settings remain unchanged.", "",
                  "Registration, dataset/source hashes, full trades, daily marked returns and stop reviews are retained locally. No 2026 or additional-coin dataset was loaded by this experiment."])
    (args.output / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Saved {args.output / 'summary.md'}", flush=True)


if __name__ == "__main__":
    main()
