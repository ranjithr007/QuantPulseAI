"""Backfill immutable Binance spot candles used by participation replay."""

import argparse
from datetime import datetime
from datetime import timedelta
from datetime import timezone

from app.collectors.binances.spot_market_collector import SpotMarketCollector
from app.config import DEFAULT_LIVE_MARKET_SYMBOLS
from app.database.sqlserver import SessionLocal
from app.governance.evidence_policy import OFFICIAL_ENTRY_TIMEFRAMES
from app.repositories.spot_market_repository import SpotMarketRepository


TIMEFRAME_MILLISECONDS = {
    "1h": 60 * 60 * 1000,
    "2h": 2 * 60 * 60 * 1000,
    "4h": 4 * 60 * 60 * 1000,
    "1d": 24 * 60 * 60 * 1000,
}


def backfill_spot_history(
    *,
    symbols=None,
    timeframes=None,
    days=550,
    end_time=None,
    collector=None,
    repository=None,
    session_factory=SessionLocal,
):
    symbols = tuple(
        dict.fromkeys(
            [
                *(str(item).upper() for item in (symbols or DEFAULT_LIVE_MARKET_SYMBOLS)),
                "ETHBTC",
            ]
        )
    )
    timeframes = tuple(timeframes or OFFICIAL_ENTRY_TIMEFRAMES)
    end = _aware_utc(end_time or datetime.now(timezone.utc))
    start = end - timedelta(days=max(1, int(days)))
    collector = collector or SpotMarketCollector()
    repository = repository or SpotMarketRepository()
    db = session_factory()
    results = []
    try:
        for symbol in symbols:
            for timeframe in timeframes:
                cursor_ms = int(start.timestamp() * 1000)
                end_ms = int(end.timestamp() * 1000)
                stored = 0
                requests = 0
                while cursor_ms <= end_ms:
                    rows = collector.get_klines(
                        symbol,
                        timeframe,
                        limit=1000,
                        start_time=cursor_ms,
                        end_time=end_ms,
                    )
                    requests += 1
                    if not rows:
                        break
                    stored += repository.save_many(db, rows)
                    next_ms = (
                        int(_aware_utc(rows[-1]["open_time"]).timestamp() * 1000)
                        + TIMEFRAME_MILLISECONDS[timeframe]
                    )
                    if next_ms <= cursor_ms:
                        break
                    cursor_ms = next_ms
                    if len(rows) < 1000:
                        break
                results.append(
                    {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "stored": stored,
                        "requests": requests,
                    }
                )
        return {
            "status": "COMPLETED",
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "rows_processed": sum(item["stored"] for item in results),
            "scopes": results,
        }
    finally:
        db.close()


def _aware_utc(value):
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--symbols",
        default=",".join(DEFAULT_LIVE_MARKET_SYMBOLS),
    )
    parser.add_argument(
        "--timeframes",
        default=",".join(OFFICIAL_ENTRY_TIMEFRAMES),
    )
    parser.add_argument("--days", type=int, default=550)
    args = parser.parse_args()
    result = backfill_spot_history(
        symbols=[item.strip() for item in args.symbols.split(",") if item.strip()],
        timeframes=[item.strip() for item in args.timeframes.split(",") if item.strip()],
        days=args.days,
    )
    print(result)


if __name__ == "__main__":
    main()
