"""Fetch public archives or run a frozen, isolated BTC/ETH research screen."""
from __future__ import annotations

import argparse
from dataclasses import replace
from hashlib import sha256
import io
import json
import re
from pathlib import Path
import sys
from urllib.request import urlopen
import zipfile

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.backtesting.spot_pullback_research import ResearchConfig, run_screen


def fetch_archives(directory, first, last, symbols=("BTCUSDT", "ETHUSDT")):
    """Only public candles leave/enter this path; no account or strategy payload."""
    symbols = validate_symbols(symbols)
    directory.mkdir(parents=True, exist_ok=True)
    manifest = []
    months = pd.period_range(first, last, freq="M")
    if len(months) == 0:
        raise ValueError("Ordered first/last months required")
    for symbol in symbols:
        pieces = []
        for month in months:
            name = f"{symbol}-15m-{month}.zip"
            url = f"https://data.binance.vision/data/spot/monthly/klines/{symbol}/15m/{name}"
            archive = directory / name
            checksum_file = directory / (name + ".CHECKSUM")
            if not archive.exists():
                with urlopen(url, timeout=45) as response:
                    archive.write_bytes(response.read())
            if not checksum_file.exists():
                with urlopen(url + ".CHECKSUM", timeout=45) as response:
                    checksum_file.write_bytes(response.read())
            content = archive.read_bytes()
            checksum = sha256(content).hexdigest()
            if checksum_file.read_text().split()[0] != checksum:
                raise ValueError(f"Checksum mismatch: {name}")
            with zipfile.ZipFile(io.BytesIO(content)) as bundle:
                names = [n for n in bundle.namelist() if n.endswith(".csv")]
                if len(names) != 1:
                    raise ValueError(f"Unexpected archive members: {name}")
                with bundle.open(names[0]) as source:
                    raw = pd.read_csv(source, header=None)
            times = raw.iloc[:, 0].astype("int64")
            unit = "us" if times.min() > 100_000_000_000_000 else "ms"
            frame = raw.iloc[:, [1, 2, 3, 4, 7]].copy()
            frame.columns = ["open", "high", "low", "close", "quote_volume"]
            frame.insert(0, "timestamp", pd.to_datetime(times, unit=unit, utc=True))
            pieces.append(frame)
            manifest.append({"symbol": symbol, "month": str(month), "url": url,
                             "sha256": checksum, "rows": len(frame), "timestamp_unit": unit})
            print(f"Verified {name}: {len(frame)} bars", flush=True)
        pd.concat(pieces, ignore_index=True).to_csv(directory / f"{symbol}.csv", index=False)
    (directory / "source_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def validate_symbols(symbols):
    symbols = tuple(symbols)
    if not symbols or len(set(symbols)) != len(symbols) or any(
        not isinstance(s, str) or re.fullmatch(r"[A-Z0-9]{2,20}USDT", s) is None for s in symbols
    ):
        raise ValueError("Use distinct uppercase USDT spot symbols")
    return symbols


def load_inputs(directory, symbols=("BTCUSDT", "ETHUSDT")):
    candles, checksums = {}, {}
    for symbol in validate_symbols(symbols):
        path = directory / f"{symbol}.csv"
        checksums[symbol] = sha256(path.read_bytes()).hexdigest()
        frame = pd.read_csv(path)
        frame.index = pd.to_datetime(frame.pop("timestamp"), utc=True)
        candles[symbol] = frame
    return candles, checksums


def write_report(report, output):
    output.mkdir(parents=True, exist_ok=False)
    (output / "result.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    lines = ["# Confidential — isolated spot-pullback historical screen", "",
             "Exploratory results only. Not an untouched holdout, paper deployment or live approval.", "",
             f"Window: {report['start']} to {report['end_exclusive']} (exclusive).", "",
             "| Scenario | Trades | Net win rate | Account return | Max drawdown | Profit factor |",
             "|---|---:|---:|---:|---:|---:|"]
    def number(value):
        return "N/A" if value is None else f"{value:.3f}"
    def percent(value):
        return "N/A" if value is None else f"{value:.3f}%"
    for name, scenario in report["scenarios"].items():
        m = scenario["metrics"]
        lines.append(f"| {name} | {m['closed_trades']} | {percent(m['net_win_rate_percent'])} | "
                     f"{percent(m['return_percent'])} | {percent(m['max_drawdown_percent'])} | {number(m['profit_factor'])} |")
    lines.extend(["", "## Decision", "", "INSUFFICIENT_FOR_PROMOTION. No automatic strategy changes.", "",
                  "Scenarios are cost/latency sensitivity checks, not independent validation folds.", "",
                  "## Limitations", ""])
    lines.extend(f"- {item}" for item in report["scenarios"]["baseline"]["limitations"])
    lines.extend(["", "Full trades, daily marked equity, stop reviews, rejection counts and provenance are in result.json.",
                  "No strategy or account data was uploaded to the public candle source."])
    (output / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("fetch", help="Download checksum-verified public monthly candles")
    fetch.add_argument("--directory", type=Path, required=True)
    fetch.add_argument("--first-month", required=True)
    fetch.add_argument("--last-month", required=True)
    run = sub.add_parser("run", help="Run on local CSV data; never sends orders")
    run.add_argument("--directory", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True, help="New directory; existing runs cannot be overwritten")
    run.add_argument("--start", required=True, help="UTC ISO timestamp, after indicator warm-up")
    run.add_argument("--end", required=True, help="UTC exclusive end")
    run.add_argument("--history-start", help="Explicit UTC start of warm-up; never silently repairs gaps")
    args = parser.parse_args()
    if args.command == "fetch":
        fetch_archives(args.directory, args.first_month, args.last_month)
        return
    if args.output.exists():
        parser.error("Output already exists; use a new experiment directory")
    candles, checksums = load_inputs(args.directory)
    if args.history_start:
        history_start = pd.Timestamp(args.history_start)
        if history_start.tzinfo is None or history_start >= pd.Timestamp(args.start):
            parser.error("history-start must be timezone-aware and precede evaluation start")
        candles = {s: f.loc[f.index >= history_start] for s, f in candles.items()}
    config = ResearchConfig()
    scenarios = {}
    for name, settings in (("baseline", config),
                           ("double_execution_cost", replace(config, execution_bps=10)),
                           ("one_bar_delay", replace(config, entry_delay_bars=1))):
        print(f"Running {name}", flush=True)
        scenarios[name] = run_screen(candles, start=args.start, end=args.end, config=settings)
        print(json.dumps(scenarios[name]["metrics"]), flush=True)
    source = Path(__file__).resolve().parents[1] / "app/backtesting/spot_pullback_research.py"
    report = {"start": args.start, "end_exclusive": args.end,
              "created_at": pd.Timestamp.now(tz="UTC").isoformat(),
              "dataset_sha256": checksums, "engine_sha256": sha256(source.read_bytes()).hexdigest(),
              "history_start": args.history_start,
              "input_rows": {s: len(f) for s, f in candles.items()},
              "scenarios": scenarios, "promotion_allowed": False}
    write_report(report, args.output)
    print(f"Saved {args.output / 'summary.md'}", flush=True)


if __name__ == "__main__":
    main()
