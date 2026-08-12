import argparse
import gzip
import json
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path

from sqlalchemy import distinct
from sqlalchemy import func
from sqlalchemy import true

from app.backtesting.walk_forward_validator import PHASE2_WALK_FORWARD_DAYS
from app.backtesting.walk_forward_validator import minimum_candles_for_folds
from app.backtesting.walk_forward_validator import phase2_walk_forward_defaults
from app.collectors.Bybit.candle_collector import CandleCollector as BybitCandleCollector
from app.collectors.binances.candle_collector import CandleCollector as BinanceCandleCollector
from app.config import DEFAULT_LIVE_MARKET_SYMBOLS
from app.database.models.market_candles import MarketCandle
from app.database.sqlserver import SessionLocal
from app.governance.evidence_policy import OFFICIAL_ENTRY_TIMEFRAMES
from app.repositories.market_repository import MarketRepository
from app.utils.timeframes import timeframe_seconds


CHECKPOINT_VERSION = "canonical_candle_history_backfill_v1"
DEFAULT_HISTORY_DAYS = 550
PAGE_LIMIT = 1500


def required_candle_counts(timeframes=OFFICIAL_ENTRY_TIMEFRAMES):
    requirements = {}
    for timeframe in timeframes:
        defaults = phase2_walk_forward_defaults(timeframe)
        requirements[timeframe] = minimum_candles_for_folds(
            defaults["train_size"],
            defaults["test_size"],
            defaults["step_size"],
            PHASE2_WALK_FORWARD_DAYS["minimum_folds"],
        )
    return requirements


def backfill_canonical_candles(
    *,
    symbols,
    timeframes=OFFICIAL_ENTRY_TIMEFRAMES,
    start,
    end,
    checkpoint_path,
    primary_collector=None,
    fallback_collector=None,
    repository=None,
    session_factory=SessionLocal,
    readiness_auditor=None,
    dry_run=False,
):
    normalized_timeframes = _validated_timeframes(timeframes)
    normalized_symbols = sorted(
        {str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()}
    )
    start_ms = _epoch_ms(start)
    end_ms = _epoch_ms(end)
    requirements = required_candle_counts(normalized_timeframes)
    plan = [
        {
            "symbol": symbol,
            "timeframe": timeframe,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "required_final_candles": requirements[timeframe],
        }
        for symbol in normalized_symbols
        for timeframe in normalized_timeframes
    ]
    if dry_run:
        return {
            "source": CHECKPOINT_VERSION,
            "status": "DRY_RUN",
            "history_days": round((end_ms - start_ms) / 86_400_000, 3),
            "total_scopes": len(plan),
            "required_candle_counts": requirements,
            "scopes": plan,
        }

    checkpoint = load_checkpoint(checkpoint_path)
    primary_collector = primary_collector or BinanceCandleCollector()
    fallback_collector = fallback_collector or BybitCandleCollector()
    repository = repository or MarketRepository()
    db = session_factory()
    completed = 0
    fetched = 0
    inserted = 0
    existing = 0
    rejected = 0
    failures = []

    try:
        for scope in plan:
            key = f"{scope['symbol']}:{scope['timeframe']}"
            prior = dict((checkpoint.get("scopes") or {}).get(key) or {})
            cursor = max(start_ms, int(prior.get("next_start_ms") or start_ms))
            interval_ms = timeframe_seconds(scope["timeframe"]) * 1000

            if prior.get("status") == "COMPLETE" and cursor > end_ms:
                completed += 1
                continue

            try:
                while cursor <= end_ms:
                    rows, source = _fetch_page(
                        primary_collector,
                        fallback_collector,
                        scope,
                        cursor,
                        end_ms,
                    )
                    if not rows:
                        final_boundary_reached = cursor >= end_ms - interval_ms
                        status = (
                            "COMPLETE"
                            if final_boundary_reached
                            else "PARTIAL_NO_DATA"
                        )
                        _update_checkpoint(
                            checkpoint,
                            key,
                            cursor,
                            status,
                            prior,
                            source,
                        )
                        save_checkpoint(checkpoint_path, checkpoint)
                        if final_boundary_reached:
                            completed += 1
                        else:
                            failures.append(
                                {
                                    "scope": key,
                                    "error": "NO_CANDLES_BEFORE_FINAL_BOUNDARY",
                                }
                            )
                        break

                    fetched += len(rows)
                    batch = repository.insert_final_candles_batch(db, rows)
                    inserted += int(batch.get("inserted") or 0)
                    existing += int(batch.get("existing") or 0)
                    rejected += int(batch.get("rejected") or 0)
                    prior["fetched"] = int(prior.get("fetched") or 0) + len(rows)
                    prior["inserted"] = int(prior.get("inserted") or 0) + int(
                        batch.get("inserted") or 0
                    )
                    prior["existing"] = int(prior.get("existing") or 0) + int(
                        batch.get("existing") or 0
                    )
                    prior["rejected"] = int(prior.get("rejected") or 0) + int(
                        batch.get("rejected") or 0
                    )
                    latest_open_ms = max(int(row["open_time_ms"]) for row in rows)
                    next_cursor = max(cursor + interval_ms, latest_open_ms + interval_ms)
                    status = "COMPLETE" if next_cursor > end_ms else "RUNNING"
                    _update_checkpoint(
                        checkpoint,
                        key,
                        next_cursor,
                        status,
                        prior,
                        source,
                    )
                    save_checkpoint(checkpoint_path, checkpoint)
                    cursor = next_cursor
                    if status == "COMPLETE":
                        completed += 1
                        break
            except Exception as exc:
                db.rollback()
                failures.append({"scope": key, "error": str(exc)[:1000]})
                _update_checkpoint(
                    checkpoint,
                    key,
                    cursor,
                    "FAILED",
                    prior,
                    prior.get("source"),
                    error=str(exc)[:1000],
                )
                save_checkpoint(checkpoint_path, checkpoint)

        readiness_auditor = readiness_auditor or audit_canonical_candle_readiness
        readiness = readiness_auditor(
            symbols=normalized_symbols,
            timeframes=normalized_timeframes,
            db=db,
        )
        return {
            "source": CHECKPOINT_VERSION,
            "status": (
                "COMPLETE"
                if completed == len(plan) and readiness["ready"]
                else "PARTIAL"
            ),
            "completed_scopes": completed,
            "total_scopes": len(plan),
            "fetched": fetched,
            "inserted": inserted,
            "existing": existing,
            "rejected": rejected,
            "failures": failures,
            "readiness": readiness,
            "checkpoint_path": str(Path(checkpoint_path).resolve()),
        }
    finally:
        db.close()


def audit_canonical_candle_readiness(
    *,
    symbols,
    timeframes=OFFICIAL_ENTRY_TIMEFRAMES,
    db=None,
    session_factory=SessionLocal,
):
    normalized_timeframes = _validated_timeframes(timeframes)
    requirements = required_candle_counts(normalized_timeframes)
    owns_session = db is None
    db = db or session_factory()
    try:
        records = []
        for symbol in sorted({str(item).upper() for item in symbols}):
            for timeframe in normalized_timeframes:
                count = (
                    db.query(func.count(distinct(MarketCandle.open_time)))
                    .filter(MarketCandle.symbol == symbol)
                    .filter(MarketCandle.timeframe == timeframe)
                    .filter(MarketCandle.is_final == true())
                    .scalar()
                    or 0
                )
                required = requirements[timeframe]
                records.append(
                    {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "final_candles": int(count),
                        "required_final_candles": int(required),
                        "ready": int(count) >= int(required),
                        "missing": max(int(required) - int(count), 0),
                    }
                )
        ready_scopes = sum(1 for record in records if record["ready"])
        return {
            "ready": ready_scopes == len(records),
            "ready_scopes": ready_scopes,
            "total_scopes": len(records),
            "records": records,
        }
    finally:
        if owns_session:
            db.close()


def export_canonical_candle_cache(
    *,
    path,
    symbols,
    timeframes=OFFICIAL_ENTRY_TIMEFRAMES,
    start,
    end,
    session_factory=SessionLocal,
):
    normalized_symbols = sorted({str(item).upper() for item in symbols})
    normalized_timeframes = _validated_timeframes(timeframes)
    start_time = _as_naive_utc(start)
    end_time = _as_naive_utc(end)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    db = session_factory()
    exported = 0
    try:
        query = (
            db.query(MarketCandle)
            .filter(MarketCandle.symbol.in_(normalized_symbols))
            .filter(MarketCandle.timeframe.in_(normalized_timeframes))
            .filter(MarketCandle.is_final == true())
            .filter(MarketCandle.open_time >= start_time)
            .filter(MarketCandle.open_time <= end_time)
            .order_by(
                MarketCandle.symbol,
                MarketCandle.timeframe,
                MarketCandle.open_time,
            )
        )
        with gzip.open(temporary, "wt", encoding="utf-8") as handle:
            for candle in query.yield_per(PAGE_LIMIT):
                handle.write(json.dumps(_cache_candle(candle)) + "\n")
                exported += 1
        temporary.replace(destination)
        return {
            "source": CHECKPOINT_VERSION,
            "status": "EXPORTED",
            "rows": exported,
            "path": str(destination.resolve()),
        }
    finally:
        db.close()


def import_canonical_candle_cache(
    *,
    path,
    symbols,
    timeframes=OFFICIAL_ENTRY_TIMEFRAMES,
    repository=None,
    session_factory=SessionLocal,
    readiness_auditor=None,
):
    normalized_symbols = sorted({str(item).upper() for item in symbols})
    normalized_timeframes = _validated_timeframes(timeframes)
    allowed_symbols = set(normalized_symbols)
    allowed_timeframes = set(normalized_timeframes)
    repository = repository or MarketRepository()
    db = session_factory()
    batch = []
    inserted = 0
    existing = 0
    rejected = 0
    read = 0
    try:
        with gzip.open(Path(path), "rt", encoding="utf-8") as handle:
            for line in handle:
                candle = json.loads(line)
                if (
                    candle.get("symbol") not in allowed_symbols
                    or candle.get("timeframe") not in allowed_timeframes
                ):
                    rejected += 1
                    continue
                batch.append(candle)
                read += 1
                if len(batch) >= PAGE_LIMIT:
                    result = repository.insert_final_candles_batch(db, batch)
                    inserted += int(result.get("inserted") or 0)
                    existing += int(result.get("existing") or 0)
                    rejected += int(result.get("rejected") or 0)
                    batch = []
            if batch:
                result = repository.insert_final_candles_batch(db, batch)
                inserted += int(result.get("inserted") or 0)
                existing += int(result.get("existing") or 0)
                rejected += int(result.get("rejected") or 0)
        readiness_auditor = readiness_auditor or audit_canonical_candle_readiness
        readiness = readiness_auditor(
            symbols=normalized_symbols,
            timeframes=normalized_timeframes,
            db=db,
        )
        return {
            "source": CHECKPOINT_VERSION,
            "status": "COMPLETE" if readiness["ready"] else "PARTIAL",
            "read": read,
            "inserted": inserted,
            "existing": existing,
            "rejected": rejected,
            "readiness": readiness,
            "path": str(Path(path).resolve()),
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
        raise ValueError("Unsupported canonical candle backfill checkpoint version")
    return payload


def save_checkpoint(path, checkpoint):
    checkpoint_path = Path(path)
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint["updated_at"] = datetime.now(timezone.utc).isoformat()
    temporary = checkpoint_path.with_suffix(checkpoint_path.suffix + ".tmp")
    temporary.write_text(json.dumps(checkpoint, indent=2), encoding="utf-8")
    temporary.replace(checkpoint_path)


def _fetch_page(primary, fallback, scope, cursor, end_ms):
    options = {
        "interval": scope["timeframe"],
        "limit": PAGE_LIMIT,
        "start_time_ms": cursor,
        "end_time_ms": end_ms,
    }
    rows = primary.get_candles(scope["symbol"], **options) or []
    if rows:
        return rows, "BINANCE_FUTURES"
    rows = fallback.get_candles(scope["symbol"], **options) or []
    return rows, "BYBIT" if rows else "NONE"


def _update_checkpoint(
    checkpoint,
    key,
    next_start_ms,
    status,
    prior,
    source,
    *,
    error=None,
):
    checkpoint.setdefault("scopes", {})[key] = {
        "next_start_ms": int(next_start_ms),
        "status": status,
        "source": source,
        "fetched": int(prior.get("fetched") or 0),
        "inserted": int(prior.get("inserted") or 0),
        "existing": int(prior.get("existing") or 0),
        "rejected": int(prior.get("rejected") or 0),
        "error": error,
    }


def _validated_timeframes(timeframes):
    normalized = tuple(str(item).strip() for item in timeframes)
    unsupported = sorted(set(normalized) - set(OFFICIAL_ENTRY_TIMEFRAMES))
    if unsupported:
        raise ValueError(
            "Unsupported governed timeframe(s): " + ", ".join(unsupported)
        )
    return normalized


def _epoch_ms(value):
    if isinstance(value, (int, float)):
        return int(value)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return int(value.timestamp() * 1000)


def _as_naive_utc(value):
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _cache_candle(candle):
    open_time = candle.open_time.replace(tzinfo=timezone.utc)
    close_time = candle.close_time.replace(tzinfo=timezone.utc)
    return {
        "symbol": str(candle.symbol).upper(),
        "timeframe": str(candle.timeframe),
        "venue": str(candle.venue or "UNKNOWN").upper(),
        "market_type": str(candle.market_type or "FUTURES").upper(),
        "source": str(candle.source or "CANONICAL_CACHE"),
        "open_time_ms": int(open_time.timestamp() * 1000),
        "close_time_ms": int(close_time.timestamp() * 1000),
        "is_final": True,
        "open": float(candle.open_price),
        "high": float(candle.high_price),
        "low": float(candle.low_price),
        "close": float(candle.close_price),
        "volume": float(candle.volume),
    }


def _default_checkpoint_path():
    return (
        Path(__file__).resolve().parents[2]
        / "outputs"
        / "canonical_candle_history_backfill.json"
    )


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Resumable canonical candle backfill for QuantPulseAI's governed "
            "1h/2h/4h/1d decision stack."
        )
    )
    parser.add_argument("--symbols", default=",".join(DEFAULT_LIVE_MARKET_SYMBOLS))
    parser.add_argument(
        "--timeframes",
        default=",".join(OFFICIAL_ENTRY_TIMEFRAMES),
    )
    parser.add_argument("--days", type=int, default=DEFAULT_HISTORY_DAYS)
    parser.add_argument("--checkpoint", default=str(_default_checkpoint_path()))
    parser.add_argument("--export-cache")
    parser.add_argument("--import-cache")
    parser.add_argument("--dry-run", action="store_true")
    arguments = parser.parse_args()
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=arguments.days)
    symbols = [item for item in arguments.symbols.split(",") if item.strip()]
    timeframes = [
        item for item in arguments.timeframes.split(",") if item.strip()
    ]
    if arguments.export_cache and arguments.import_cache:
        parser.error("--export-cache and --import-cache are mutually exclusive")
    if arguments.export_cache:
        result = export_canonical_candle_cache(
            path=arguments.export_cache,
            symbols=symbols,
            timeframes=timeframes,
            start=start,
            end=end,
        )
    elif arguments.import_cache:
        result = import_canonical_candle_cache(
            path=arguments.import_cache,
            symbols=symbols,
            timeframes=timeframes,
        )
    else:
        result = backfill_canonical_candles(
            symbols=symbols,
            timeframes=timeframes,
            start=start,
            end=end,
            checkpoint_path=arguments.checkpoint,
            dry_run=arguments.dry_run,
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
