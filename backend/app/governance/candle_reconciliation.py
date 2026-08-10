import argparse
import json
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path

from app.collectors.Bybit.candle_collector import (
    CandleCollector as BybitCandleCollector,
)
from app.collectors.binances.candle_collector import CandleCollector
from app.database.sqlserver import SessionLocal
from app.database.sqlserver import USING_SQLITE_FALLBACK
from app.governance.evidence_policy import OFFICIAL_ENTRY_TIMEFRAMES
from app.market_data.reconciliation import load_reconciliation_checkpoint
from app.market_data.reconciliation import reconcile_scope
from app.repositories.market_repository import MarketRepository


def run_candle_reconciliation(
    *,
    symbols,
    timeframes=OFFICIAL_ENTRY_TIMEFRAMES,
    start_time,
    end_time,
    checkpoint_path,
    page_size=1000,
    max_pages=1,
    compare_bybit=False,
    audit_only=False,
):
    if USING_SQLITE_FALLBACK:
        raise RuntimeError(
            "R1 reconciliation refuses SQLite fallback; SQL Server is required."
        )

    checkpoint = load_reconciliation_checkpoint(checkpoint_path)
    db = SessionLocal()
    repository = MarketRepository()
    primary = CandleCollector()
    secondary = BybitCandleCollector() if compare_bybit else None
    results = []

    try:
        for symbol in symbols:
            for timeframe in timeframes:
                results.append(
                    reconcile_scope(
                        db,
                        repository,
                        primary,
                        symbol=symbol,
                        timeframe=timeframe,
                        start_time_ms=_timestamp_ms(start_time),
                        end_time_ms=_timestamp_ms(end_time),
                        checkpoint=checkpoint,
                        checkpoint_path=checkpoint_path,
                        secondary_collector=secondary,
                        page_size=page_size,
                        max_pages=max_pages,
                        audit_only=audit_only,
                    )
                )
        return {
            "source": "r1_candle_reconciliation",
            "status": (
                "PASS"
                if all(item["status"] == "PASS" for item in results)
                else "IN_PROGRESS"
            ),
            "audit_only": bool(audit_only),
            "symbols": [item.upper() for item in symbols],
            "timeframes": list(timeframes),
            "checkpoint_path": str(Path(checkpoint_path).resolve()),
            "results": results,
        }
    finally:
        db.close()


def _timestamp_ms(value):
    timestamp = value
    if not isinstance(timestamp, datetime):
        timestamp = datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return int(timestamp.astimezone(timezone.utc).timestamp() * 1000)


def _default_checkpoint_path():
    return (
        Path(__file__).resolve().parents[3]
        / "outputs"
        / "r1_candle_reconciliation_checkpoint.json"
    )


def _default_report_path():
    return (
        Path(__file__).resolve().parents[3]
        / "outputs"
        / "r1_candle_reconciliation_audit_2026-07-27.json"
    )


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Resume canonical Binance futures candle reconciliation and "
            "optionally compare overlapping Bybit candles."
        )
    )
    parser.add_argument("--symbols", required=True)
    parser.add_argument(
        "--timeframes",
        default=",".join(OFFICIAL_ENTRY_TIMEFRAMES),
    )
    parser.add_argument(
        "--start",
        default=(
            datetime.now(timezone.utc) - timedelta(days=30)
        ).isoformat(),
    )
    parser.add_argument(
        "--end",
        default=datetime.now(timezone.utc).isoformat(),
    )
    parser.add_argument(
        "--checkpoint",
        default=str(_default_checkpoint_path()),
    )
    parser.add_argument("--report", default=None)
    parser.add_argument("--page-size", type=int, default=1000)
    parser.add_argument("--max-pages", type=int, default=1)
    parser.add_argument("--compare-bybit", action="store_true")
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--summary-only", action="store_true")
    arguments = parser.parse_args()

    result = run_candle_reconciliation(
        symbols=_csv(arguments.symbols),
        timeframes=_csv(arguments.timeframes),
        start_time=arguments.start,
        end_time=arguments.end,
        checkpoint_path=arguments.checkpoint,
        page_size=max(1, min(arguments.page_size, 1500)),
        max_pages=max(1, arguments.max_pages),
        compare_bybit=arguments.compare_bybit,
        audit_only=arguments.audit_only,
    )
    if arguments.report:
        report_path = Path(arguments.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(result, indent=2, default=str),
            encoding="utf-8",
        )
        result["report_path"] = str(report_path.resolve())
    printable = (
        {
            "source": result["source"],
            "status": result["status"],
            "audit_only": result["audit_only"],
            "checkpoint_path": result["checkpoint_path"],
            "report_path": result.get("report_path"),
            "results": [
                {
                    "scope": item["scope"],
                    "status": item["status"],
                    "pages_processed": item["pages_processed"],
                    "write_status_counts": item["write_status_counts"],
                    "sequence_status": item["sequence"]["status"],
                    "coverage_status": item["coverage"]["status"],
                    "expected_count": item["coverage"]["expected_count"],
                    "observed_count": item["coverage"]["observed_count"],
                    "missing_count": item["coverage"]["missing_count"],
                    "source_comparisons": [
                        {
                            "status": comparison["status"],
                            "overlap_count": comparison["overlap_count"],
                            "price_disagreement_count": comparison[
                                "price_disagreement_count"
                            ],
                            "volume_context_difference_count": comparison[
                                "volume_context_difference_count"
                            ],
                        }
                        for comparison in item["source_comparisons"]
                    ],
                }
                for item in result["results"]
            ],
        }
        if arguments.summary_only
        else result
    )
    print(json.dumps(printable, indent=2, default=str))


def _csv(value):
    return [
        item.strip()
        for item in str(value or "").split(",")
        if item.strip()
    ]


if __name__ == "__main__":
    main()
