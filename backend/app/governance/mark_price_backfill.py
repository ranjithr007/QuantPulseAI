import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.collectors.binances.mark_price_collector import MarkPriceCollector
from app.config import DEFAULT_LIVE_MARKET_SYMBOLS
from app.database.sqlserver import SessionLocal
from app.repositories.derivative_repository import DerivativeRepository
from app.governance.evidence_policy import OFFICIAL_ENTRY_TIMEFRAMES


CHECKPOINT_VERSION = "r4_mark_price_backfill_v1"
OFFICIAL_TIMEFRAMES = OFFICIAL_ENTRY_TIMEFRAMES
TIMEFRAME_MILLISECONDS = {
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}


def backfill_mark_prices(
    *,
    symbols,
    timeframes=OFFICIAL_TIMEFRAMES,
    start,
    end,
    checkpoint_path,
    collector=None,
    repository=None,
    session_factory=SessionLocal,
    dry_run=False,
):
    start_ms = _epoch_ms(start)
    end_ms = _epoch_ms(end)
    checkpoint = load_checkpoint(checkpoint_path)
    plan = [
        {
            "symbol": symbol.upper(),
            "timeframe": timeframe,
            "start_ms": start_ms,
            "end_ms": end_ms,
        }
        for symbol in symbols
        for timeframe in timeframes
    ]
    if dry_run:
        return {
            "status": "DRY_RUN",
            "checkpoint_version": CHECKPOINT_VERSION,
            "scopes": plan,
        }

    collector = collector or MarkPriceCollector()
    repository = repository or DerivativeRepository()
    db = session_factory()
    completed = 0
    inserted_or_updated = 0
    try:
        for scope in plan:
            key = f"{scope['symbol']}:{scope['timeframe']}"
            prior = (checkpoint.get("scopes") or {}).get(key) or {}
            cursor = max(start_ms, int(prior.get("next_start_ms") or start_ms))
            while cursor <= end_ms:
                rows = collector.get_klines(
                    scope["symbol"],
                    scope["timeframe"],
                    limit=1500,
                    start_time_ms=cursor,
                    end_time_ms=end_ms,
                )
                if not rows:
                    final_boundary_reached = (
                        cursor
                        >= end_ms
                        - TIMEFRAME_MILLISECONDS[scope["timeframe"]]
                    )
                    _update_checkpoint(
                        checkpoint,
                        key,
                        cursor,
                        (
                            "COMPLETE_FINAL_BOUNDARY"
                            if final_boundary_reached
                            else "PARTIAL_NO_DATA"
                        ),
                        prior.get("rows", 0),
                    )
                    save_checkpoint(checkpoint_path, checkpoint)
                    if final_boundary_reached:
                        completed += 1
                    break
                repository.save_mark_prices(db, rows)
                inserted_or_updated += len(rows)
                prior["rows"] = int(prior.get("rows") or 0) + len(rows)
                last_close_ms = _epoch_ms(rows[-1]["close_time"])
                cursor = max(cursor + 1, last_close_ms + 1)
                status = "COMPLETE" if cursor > end_ms else "RUNNING"
                _update_checkpoint(
                    checkpoint,
                    key,
                    cursor,
                    status,
                    prior["rows"],
                )
                save_checkpoint(checkpoint_path, checkpoint)
                if status == "COMPLETE":
                    completed += 1
                    break
        return {
            "status": "COMPLETE" if completed == len(plan) else "PARTIAL",
            "completed_scopes": completed,
            "total_scopes": len(plan),
            "rows_processed": inserted_or_updated,
            "checkpoint_path": str(Path(checkpoint_path).resolve()),
        }
    finally:
        db.close()


def new_checkpoint():
    return {
        "checkpoint_version": CHECKPOINT_VERSION,
        "updated_at": None,
        "scopes": {},
    }


def load_checkpoint(path):
    checkpoint_path = Path(path)
    if not checkpoint_path.exists():
        return new_checkpoint()
    payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    if payload.get("checkpoint_version") != CHECKPOINT_VERSION:
        raise ValueError("Unsupported mark-price backfill checkpoint version")
    return payload


def save_checkpoint(path, checkpoint):
    checkpoint_path = Path(path)
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint["updated_at"] = datetime.now(timezone.utc).isoformat()
    temporary = checkpoint_path.with_suffix(checkpoint_path.suffix + ".tmp")
    temporary.write_text(json.dumps(checkpoint, indent=2), encoding="utf-8")
    temporary.replace(checkpoint_path)


def _update_checkpoint(checkpoint, key, next_start_ms, status, rows):
    checkpoint.setdefault("scopes", {})[key] = {
        "next_start_ms": int(next_start_ms),
        "status": status,
        "rows": int(rows),
    }


def _epoch_ms(value):
    if isinstance(value, (int, float)):
        return int(value)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return int(value.timestamp() * 1000)


def _default_checkpoint_path():
    return (
        Path(__file__).resolve().parents[3]
        / "outputs"
        / "r4_mark_price_backfill_checkpoint.json"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Resumable Binance futures mark-price backfill.",
    )
    parser.add_argument(
        "--symbols",
        default=",".join(DEFAULT_LIVE_MARKET_SYMBOLS),
    )
    parser.add_argument("--timeframes", default=",".join(OFFICIAL_TIMEFRAMES))
    parser.add_argument("--days", type=int, default=540)
    parser.add_argument("--checkpoint", default=str(_default_checkpoint_path()))
    parser.add_argument("--dry-run", action="store_true")
    arguments = parser.parse_args()
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=arguments.days)
    result = backfill_mark_prices(
        symbols=[item.strip() for item in arguments.symbols.split(",") if item.strip()],
        timeframes=[
            item.strip()
            for item in arguments.timeframes.split(",")
            if item.strip()
        ],
        start=start,
        end=end,
        checkpoint_path=arguments.checkpoint,
        dry_run=arguments.dry_run,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
