"""Register before acquiring reserved data, then run six frozen transfer tests."""
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
from app.backtesting.spot_pullback_comparison import diagnostics, validate_policy
from run_spot_pullback_research import fetch_archives, load_inputs

PLAN = ROOT / "docs/spot-trend-validation-plan.json"
SOURCES = [Path(__file__), ROOT / "app/backtesting/spot_pullback_research.py",
           ROOT / "app/backtesting/spot_pullback_comparison.py",
           ROOT / "scripts/run_spot_pullback_research.py"]


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def dump(path, obj):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(obj, stream, indent=2, allow_nan=False)


def verify(output):
    registration = json.loads((output / "registration.json").read_text())
    if digest(PLAN) != registration["plan_sha256"]:
        raise ValueError("Registered plan changed; this validation cannot proceed")
    for path in SOURCES:
        if digest(path) != registration["source_sha256"][str(path.relative_to(ROOT))]:
            raise ValueError("Registered source changed; this validation cannot proceed")
    return registration


def register(output, reference):
    plan = json.loads(PLAN.read_text())
    validate_policy(plan["policy"])
    prior = json.loads((reference / "registration.json").read_text())
    previous_policy = next(p for p in prior["plan"]["candidates"] if p["id"] == "B1_TREND_ONLY")
    if previous_policy != plan["policy"]:
        raise ValueError("Frozen B1 policy differs from prior experiment")
    feature_source = ROOT / "app/backtesting/spot_pullback_comparison.py"
    if digest(feature_source) != prior["source_sha256"][str(feature_source.relative_to(ROOT))]:
        raise ValueError("Frozen signal-feature implementation differs from prior experiment")
    output.mkdir(parents=True, exist_ok=False)
    dump(output / "registration.json", {
        "recorded_before_data_acquisition_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "plan": plan, "plan_sha256": digest(PLAN),
        "source_sha256": {str(p.relative_to(ROOT)): digest(p) for p in SOURCES},
        "reference_registration_sha256": digest(reference / "registration.json"),
        "reference_directory": str(reference.resolve()),
        "frozen_signal_source_verified": True,
        "engine_revision_note": "Added explicit tradable-symbol whitelist so BTC context cannot enter the altcoin cohort; original default preserved.",
        "promotion_allowed": False,
    })


def execute(output):
    registration = verify(output)
    plan = registration["plan"]
    data = plan["data"]
    dump(output / "started.json", {"started_at": pd.Timestamp.now(tz="UTC").isoformat()})
    frames, hashes = load_inputs(output / "data", data["symbols"])
    frames = {s: f.loc[(f.index >= pd.Timestamp(data["history_start"])) &
                      (f.index < pd.Timestamp(data["end"]))] for s, f in frames.items()}
    dump(output / "data_provenance.json", {"csv_sha256": hashes,
         "archive_manifest_sha256": digest(output / "data/source_manifest.json"),
         "rows": {s: len(f) for s, f in frames.items()},
         "novelty": data["novelty"]})
    rows = []
    for cohort in plan["cohorts"]:
        required = set(cohort["traded_symbols"]) | set(cohort["context_symbols"])
        inputs = {s: frames[s] for s in sorted(required)}
        for scenario in plan["scenarios"]:
            name = cohort["id"] + "_" + scenario["id"]
            print(f"Running {name}", flush=True)
            settings = ResearchConfig(**{k: v for k, v in scenario.items() if k != "id"})
            try:
                result = run_screen(inputs, start=data["start"], end=data["end"], config=settings,
                                    policy=plan["policy"], tradable_symbols=cohort["traded_symbols"])
            except ValueError as exc:
                failure = {"name": name, "status": "FAILED_DATA_OR_VALIDATION", "reason": str(exc),
                           "promotion_allowed": False}
                dump(output / (name + ".json"), failure)
                rows.append(failure)
                print(json.dumps(failure), flush=True)
                continue
            result["diagnostics"] = diagnostics(result)
            result["experiment_role"] = "FROZEN_TEMPORAL_AND_ASSET_TRANSFER_TEST"
            result["limitations"] = [
                "Previously selected rule; 2026 data is new to this research sequence, prior access elsewhere unknown.",
                "Fixed purposive asset sample, not a reconstructed universe or proof for every coin.",
                "OHLCV cannot verify spread/depth, limit fills, lot sizes, event vetoes or operational execution.",
                "Current fee scenario, assumed execution cost and quote-equivalent fees; no historical fee-tier reconstruction.",
                "Conservative synchronized-low marks are not observed tick paths; gaps can exceed risk budgets.",
                "Separate wallets and overlapping stress trials cannot be pooled as independent evidence.",
                "No forward paper evidence or live promotion; this accessed period is no longer unseen.",
            ]
            curve = result.pop("equity_curve")
            with gzip.open(output / (name + "_equity.json.gz"), "xt", encoding="utf-8") as stream:
                json.dump(curve, stream, allow_nan=False)
            result["equity_curve_file"] = name + "_equity.json.gz"
            dump(output / (name + ".json"), result)
            row = {"name": name, "cohort": cohort["id"], "scenario": scenario["id"],
                   "status": "COMPLETED", "metrics": result["metrics"],
                   "diagnostics": result["diagnostics"], "risk_events": result["risk_events"],
                   "all_assets_positive": all(item["trades"] > 0 and item["net_pnl"] > 0
                                              for item in result["diagnostics"]["by_symbol"].values())}
            rows.append(row)
            print(json.dumps({"name": name, **result["metrics"]}), flush=True)
    verify(output)
    # Recheck the price inputs after all runs as well as code/plan provenance.
    if any(digest(output / "data" / f"{s}.csv") != hashes[s] for s in data["symbols"]):
        raise ValueError("Price inputs changed during validation")
    gates = []
    for row in rows:
        if row["status"] != "COMPLETED":
            gates.append({"name": row["name"], "failed": ["data_validation"]})
            continue
        m = row["metrics"]
        failed = []
        if m["closed_trades"] < plan["acceptance"]["minimum_trades_per_cohort"]:
            failed.append("insufficient_trade_count")
        if m["expectancy_quote"] is None or m["expectancy_quote"] <= 0:
            failed.append("nonpositive_expectancy")
        if m["profit_factor"] is None or m["profit_factor"] < plan["acceptance"]["minimum_profit_factor"]:
            failed.append("profit_factor")
        if m["max_drawdown_percent"] > plan["acceptance"]["maximum_drawdown_percent"]:
            failed.append("drawdown")
        if not row["all_assets_positive"]:
            failed.append("asset_consistency")
        gates.append({"name": row["name"], "failed": failed})
    report = {"experiment_id": plan["experiment_id"], "runs": rows, "gates": gates,
              "promotion_allowed": False, "status": "VALIDATION_REVIEW_REQUIRED",
              "window": data, "period_consumed_as_validation": True}
    dump(output / "validation.json", report)
    lines = ["# Confidential — frozen trend validation", "",
             "January–August 2026; no rule changes after registration or price access.", "",
             "| Cohort / scenario | Trades | Net win rate | Account return | Max drawdown | Profit factor |",
             "|---|---:|---:|---:|---:|---:|"]
    def fmt(value, pct=False):
        return "N/A" if value is None else f"{value:.3f}" + ("%" if pct else "")
    for row in rows:
        if row["status"] != "COMPLETED":
            lines.append(f"| {row['name']} | FAILED | — | — | — | — |")
        else:
            m = row["metrics"]
            lines.append(f"| {row['name']} | {m['closed_trades']} | {fmt(m['net_win_rate_percent'], True)} | "
                         f"{fmt(m['return_percent'], True)} | {fmt(m['max_drawdown_percent'], True)} | {fmt(m['profit_factor'])} |")
    lines.extend(["", "## Decision gates", ""])
    lines.extend(f"- {g['name']}: {', '.join(g['failed']) or 'observed numeric gates passed; deployment still prohibited'}." for g in gates)
    lines.extend(["", "## Scope", "",
                  "Majors: BTC/ETH. Additional coins: SOL/XRP/BNB, with BTC used only for context. Each cohort has its own hypothetical 10,000-quote-unit wallet; returns are not additive.", "",
                  "Fees remain 10 bps per side; base execution allowance remains an unmeasured 5 bps per side. The stress scenarios rerun admission gates, so their trade populations differ.", "",
                  "No guarantee this period was unseen elsewhere. The extra coins form a purposive surviving-asset sample, not an unbiased market universe. Execution/event/universe and prospective paper validation remain missing. No 80% claim or live/paper deployment is authorized.", "",
                  "This period is now consumed as validation evidence; future tuning cannot reuse it as an untouched holdout.", "",
                  "See validation.json for asset attribution, descriptive weekly-block daily-return intervals and failed gates; named run files contain trades and stop reviews. Registration and data provenance record local hashes."])
    (output / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Saved {output / 'summary.md'}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["register", "fetch", "run"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference", type=Path)
    args = parser.parse_args()
    if args.command == "register":
        if args.reference is None:
            parser.error("register requires the previous comparison directory")
        register(args.output, args.reference)
    elif args.command == "fetch":
        plan = verify(args.output)["plan"]
        fetch_archives(args.output / "data", plan["data"]["first_archive_month"],
                       plan["data"]["last_archive_month"], plan["data"]["symbols"])
    else:
        execute(args.output)


if __name__ == "__main__":
    main()
