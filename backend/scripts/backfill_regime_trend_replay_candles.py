"""Bounded Binance 5m futures candle backfill for Regime Trend replay."""

import argparse
import json
import os
from datetime import datetime, timezone

from app.collectors.binances.candle_collector import CandleCollector
from app.database.runtime import SessionLocal, normalize_database_url
from app.repositories.market_repository import MarketRepository


def parse_utc(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", required=True, help="Comma-separated symbols")
    parser.add_argument("--start", required=True, help="UTC ISO start")
    parser.add_argument("--end", required=True, help="UTC ISO end")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    symbols = sorted({item.strip().upper() for item in args.symbols.split(",") if item.strip()})
    start_ms = int(parse_utc(args.start).timestamp() * 1000)
    end_ms = int(parse_utc(args.end).timestamp() * 1000)
    plan = {"symbols": symbols, "timeframe": "5m", "start": args.start, "end": args.end}
    if args.dry_run:
        print(json.dumps({"status": "DRY_RUN", **plan}, indent=2))
        return
    if not os.getenv("QUANTPULSE_DATABASE_URL"):
        raise SystemExit("QUANTPULSE_DATABASE_URL is required")
    collector = CandleCollector()
    repository = MarketRepository()
    db = SessionLocal()
    totals = {"fetched": 0, "inserted": 0, "existing": 0, "rejected": 0}
    try:
        for symbol in symbols:
            cursor = start_ms
            while cursor <= end_ms:
                rows = collector.get_candles(
                    symbol, interval="5m", limit=1500,
                    start_time_ms=cursor, end_time_ms=end_ms,
                )
                if not rows:
                    break
                batch = repository.insert_final_candles_batch(db, rows)
                totals["fetched"] += len(rows)
                for key in ("inserted", "existing", "rejected"):
                    totals[key] += int(batch.get(key) or 0)
                latest = max(int(row["open_time_ms"]) for row in rows)
                next_cursor = latest + 300_000
                if next_cursor <= cursor:
                    raise RuntimeError(f"collector made no progress for {symbol}")
                cursor = next_cursor
        print(json.dumps({"status": "COMPLETE", **plan, **totals}, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
