"""Bounded read-only Binance depth sampling; never places or tests an order."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import statistics
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.backtesting.spot_execution_probe import estimate_book_cost

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT")
SIZES = (100, 1000, 2500)
BASE = "https://data-api.binance.vision"


def utc():
    return datetime.now(timezone.utc).isoformat()


def sample(symbol):
    started, clock = utc(), time.monotonic()
    url = BASE + "/api/v3/depth?symbol=" + symbol + "&limit=100"
    try:
        with urlopen(url, timeout=10) as response:
            raw = response.read()
            date = response.headers.get("Date")
        book = json.loads(raw)
        return {"symbol": symbol, "requested_at": started, "received_at": utc(),
                "latency_seconds": time.monotonic() - clock, "http_date": date,
                "response_sha256": sha256(raw).hexdigest(), "url": url, "book": book}
    except HTTPError as exc:
        return {"symbol": symbol, "requested_at": started, "received_at": utc(),
                "error": "HTTP_" + str(exc.code), "url": url}
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        return {"symbol": symbol, "requested_at": started, "received_at": utc(),
                "error": type(exc).__name__ + ": " + str(exc), "url": url}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    plan = {"started_at": utc(), "symbols": SYMBOLS, "quote_notionals": SIZES,
            "rounds": 12, "interval_seconds": 10, "depth_levels": 100,
            "maximum_accepted_request_seconds": 3, "fee_bps_per_side_assumption": 10,
            "endpoint": BASE + "/api/v3/depth", "read_only": True,
            "minimum_unique_usable_snapshots_per_symbol": 8,
            "purpose": "Short displayed-liquidity feasibility probe, not fill or tail-cost validation",
            "code_sha256": {p.name: sha256(p.read_bytes()).hexdigest() for p in (
                Path(__file__), ROOT / "app/backtesting/spot_execution_probe.py")}}
    (args.output / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    records, samples, seen, status = [], [], {}, "COMPLETED"
    with (args.output / "raw_snapshots.jsonl").open("x", encoding="utf-8") as log:
        with ThreadPoolExecutor(max_workers=5) as pool:
            for round_id in range(plan["rounds"]):
                began = time.monotonic()
                current = list(pool.map(sample, SYMBOLS))
                for row in current:
                    row["round"] = round_id + 1
                    row["usable"] = False
                    if "error" not in row:
                        update = row["book"].get("lastUpdateId")
                        if not isinstance(update, int) or update <= seen.get(row["symbol"], -1):
                            row["rejected"] = "MISSING_OR_NONINCREASING_UPDATE_ID"
                        elif row["latency_seconds"] > plan["maximum_accepted_request_seconds"]:
                            row["rejected"] = "SLOW_REQUEST"
                        else:
                            try:
                                estimates = [estimate_book_cost(row["book"], n) for n in SIZES]
                                samples.extend({"symbol": row["symbol"], "round": round_id + 1, **item}
                                               for item in estimates)
                                row["usable"] = True
                            except (ValueError, KeyError, TypeError) as exc:
                                row["rejected"] = str(exc)
                        if isinstance(update, int):
                            seen[row["symbol"]] = max(seen.get(row["symbol"], -1), update)
                    log.write(json.dumps(row, allow_nan=False) + "\n")
                    log.flush()
                    records.append(row)
                print(f"Round {round_id + 1}: {sum(r['usable'] for r in current)}/5 usable books", flush=True)
                if any(row.get("error") in ("HTTP_418", "HTTP_429", "HTTP_451", "HTTP_403") for row in current):
                    status = "STOPPED_ON_ACCESS_OR_RATE_LIMIT"
                    break
                if all("error" in row for row in current):
                    status = "STOPPED_ON_CONNECTION_FAILURE"
                    break
                if round_id < plan["rounds"] - 1:
                    time.sleep(max(0, plan["interval_seconds"] - (time.monotonic() - began)))
    summaries = []
    for symbol in SYMBOLS:
        for size in SIZES:
            selected = [s for s in samples if s["symbol"] == symbol and s["quote_notional"] == size]
            count = len(selected)
            summary = {"symbol": symbol, "quote_notional": size, "usable_snapshots": count,
                       "sample_complete": count >= plan["minimum_unique_usable_snapshots_per_symbol"]}
            for key in ("top_spread_bps", "displayed_round_trip_bps", "indicative_total_round_trip_bps"):
                summary["median_" + key] = statistics.median(s[key] for s in selected) if count else None
                summary["maximum_observed_" + key] = max((s[key] for s in selected), default=None)
            summaries.append(summary)
    result = {"status": status, "finished_at": utc(), "plan": plan, "summary": summaries,
              "estimates": samples, "request_failures": [{k: v for k, v in row.items() if k != "book"}
                  for row in records if not row["usable"]], "promotion_allowed": False,
              "raw_log_sha256": sha256((args.output / "raw_snapshots.jsonl").read_bytes()).hexdigest(),
              "limitations": ["Approximately two minutes, one session; not representative of volatility, sessions or weekends.",
                  "Displayed depth can disappear; no actual fill, queue, adverse-selection or latency-loss measurement.",
                  "REST depth has an update ID but no exchange event timestamp; local receipt time is not exchange freshness.",
                  "No lot/minimum-notional or fee-asset accounting; quoted sizes are illustrative USDT amounts.",
                  "Immediate two-sided book sweep, not a strategy holding-period return or realistic simultaneous execution.",
                  "Historical slippage assumptions must not be replaced by this short current sample."]}
    (args.output / "result.json").write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    lines = ["# Confidential — public order-book feasibility probe", "", f"Status: {status}", "",
             "Read-only sampling. No orders, account access or executable-fill claims.", "",
             "| Symbol | USDT notional | Usable snapshots | Median displayed round trip (bps) | Median incl. assumed fees (bps) |",
             "|---|---:|---:|---:|---:|"]
    def fmt(value):
        return "N/A" if value is None else f"{value:.4f}"
    for row in summaries:
        lines.append(f"| {row['symbol']} | {row['quote_notional']} | {row['usable_snapshots']} | "
                     f"{fmt(row['median_displayed_round_trip_bps'])} | {fmt(row['median_indicative_total_round_trip_bps'])} |")
    lines.extend(["", "Fee assumption: 0.10% per side, not an account-specific confirmation.", ""])
    lines.extend("- " + item for item in result["limitations"])
    lines.extend(["", "Source: https://developers.binance.com/docs/binance-spot-api-docs/faqs/market_data_only",
                  "Raw snapshots, receipt timestamps, request latency, update IDs and hashes are retained locally."])
    (args.output / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Saved {args.output / 'summary.md'}", flush=True)


if __name__ == "__main__":
    main()
