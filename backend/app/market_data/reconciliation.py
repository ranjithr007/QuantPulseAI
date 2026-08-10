import json
from datetime import datetime
from datetime import timezone
from pathlib import Path

from app.market_data.quality import analyze_candle_sequence
from app.market_data.quality import assess_window_coverage
from app.market_data.quality import compare_candle_sources
from app.repositories._db_utils import commit_or_rollback
from app.utils.timeframes import timeframe_seconds


CHECKPOINT_VERSION = "r1_candle_reconciliation_v1"


def reconcile_scope(
    db,
    repository,
    primary_collector,
    *,
    symbol,
    timeframe,
    start_time_ms,
    end_time_ms,
    checkpoint,
    checkpoint_path,
    secondary_collector=None,
    page_size=1000,
    max_pages=1,
    audit_only=False,
):
    scope_key = f"{symbol.upper()}:{timeframe}"
    scope = (checkpoint.get("scopes") or {}).get(scope_key) or {}
    scope_start_time_ms = scope.get("start_time_ms")
    can_resume = (
        scope_start_time_ms is not None
        and int(scope_start_time_ms) <= int(start_time_ms)
    )
    cursor_ms = (
        max(
            int(start_time_ms),
            int(scope.get("next_start_time_ms") or start_time_ms),
        )
        if can_resume
        else int(start_time_ms)
    )
    interval_ms = timeframe_seconds(timeframe) * 1000
    status_counts = {}
    source_comparisons = []
    pages_processed = 0

    if audit_only and secondary_collector is not None:
        comparison_start_ms = max(
            int(start_time_ms),
            int(end_time_ms) - (int(page_size) * interval_ms),
        )
        primary_sample = primary_collector.get_candles(
            symbol,
            interval=timeframe,
            limit=page_size,
            start_time_ms=comparison_start_ms,
            end_time_ms=end_time_ms,
        ) or []
        secondary_sample = secondary_collector.get_candles(
            symbol,
            interval=timeframe,
            limit=page_size,
            start_time_ms=comparison_start_ms,
            end_time_ms=end_time_ms,
        ) or []
        comparison = compare_candle_sources(
            _final_candles(primary_sample),
            _final_candles(secondary_sample),
        )
        comparison.update(
            {
                "sample_start_time_ms": comparison_start_ms,
                "sample_end_time_ms": int(end_time_ms),
            }
        )
        source_comparisons.append(comparison)

    if not audit_only:
        while cursor_ms < int(end_time_ms) and pages_processed < int(max_pages):
            page = primary_collector.get_candles(
                symbol,
                interval=timeframe,
                limit=page_size,
                start_time_ms=cursor_ms,
                end_time_ms=end_time_ms,
            ) or []
            page = sorted(page, key=lambda item: item["open_time_ms"])
            if not page:
                break

            for candle in page:
                result = repository.upsert_candle(
                    db,
                    candle,
                    commit=False,
                )
                status_counts[result] = status_counts.get(result, 0) + 1
            commit_or_rollback(db)

            if secondary_collector is not None:
                secondary = secondary_collector.get_candles(
                    symbol,
                    interval=timeframe,
                    limit=len(page),
                    start_time_ms=page[0]["open_time_ms"],
                    end_time_ms=page[-1]["open_time_ms"],
                ) or []
                source_comparisons.append(
                    compare_candle_sources(page, secondary)
                )

            cursor_ms = page[-1]["open_time_ms"] + interval_ms
            pages_processed += 1
            _update_scope_checkpoint(
                checkpoint,
                scope_key,
                symbol=symbol,
                timeframe=timeframe,
                start_time_ms=start_time_ms,
                next_start_time_ms=cursor_ms,
                end_time_ms=end_time_ms,
                status=(
                    "COMPLETE"
                    if cursor_ms >= int(end_time_ms)
                    else "IN_PROGRESS"
                ),
                pages_processed=(
                    int(scope.get("pages_processed") or 0)
                    + pages_processed
                ),
            )
            save_reconciliation_checkpoint(checkpoint_path, checkpoint)

            if len(page) < int(page_size):
                break

    start_time = _naive_utc(start_time_ms)
    end_time = _naive_utc(end_time_ms)
    stored = repository.get_source_candles(
        db,
        symbol.upper(),
        timeframe,
        "BINANCE",
        start_time,
        end_time,
    )
    sequence = analyze_candle_sequence(stored, timeframe)
    coverage = assess_window_coverage(
        stored,
        timeframe,
        start_time_ms=start_time_ms,
        end_time_ms=end_time_ms,
    )
    completed = cursor_ms >= int(end_time_ms)
    sources_pass = all(
        item.get("status") == "PASS"
        for item in source_comparisons
    )
    result_status = (
        "PASS"
        if (
            completed
            and sequence["status"] == "PASS"
            and coverage["status"] == "PASS"
            and sources_pass
        )
        else "IN_PROGRESS"
        if not audit_only
        else (
            "PASS"
            if sequence["status"] == "PASS"
            and coverage["status"] == "PASS"
            and sources_pass
            else "FAIL"
        )
    )

    return {
        "scope": scope_key,
        "status": result_status,
        "audit_only": bool(audit_only),
        "start_time_ms": int(start_time_ms),
        "end_time_ms": int(end_time_ms),
        "next_start_time_ms": cursor_ms,
        "pages_processed": pages_processed,
        "write_status_counts": status_counts,
        "sequence": sequence,
        "coverage": coverage,
        "source_comparisons": source_comparisons,
    }


def new_reconciliation_checkpoint():
    return {
        "checkpoint_version": CHECKPOINT_VERSION,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "scopes": {},
    }


def load_reconciliation_checkpoint(path):
    checkpoint_path = Path(path)
    if not checkpoint_path.exists():
        return new_reconciliation_checkpoint()
    payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    if payload.get("checkpoint_version") != CHECKPOINT_VERSION:
        raise ValueError("Unsupported candle reconciliation checkpoint version")
    payload.setdefault("scopes", {})
    return payload


def save_reconciliation_checkpoint(path, checkpoint):
    checkpoint_path = Path(path)
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint["updated_at"] = datetime.now(timezone.utc).isoformat()
    temporary_path = checkpoint_path.with_suffix(
        checkpoint_path.suffix + ".tmp"
    )
    temporary_path.write_text(
        json.dumps(checkpoint, indent=2, default=str),
        encoding="utf-8",
    )
    temporary_path.replace(checkpoint_path)


def _update_scope_checkpoint(
    checkpoint,
    scope_key,
    *,
    symbol,
    timeframe,
    start_time_ms,
    next_start_time_ms,
    end_time_ms,
    status,
    pages_processed,
):
    checkpoint.setdefault("scopes", {})[scope_key] = {
        "symbol": symbol.upper(),
        "timeframe": timeframe,
        "start_time_ms": int(start_time_ms),
        "next_start_time_ms": int(next_start_time_ms),
        "end_time_ms": int(end_time_ms),
        "status": status,
        "pages_processed": int(pages_processed),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _naive_utc(timestamp_ms):
    return datetime.fromtimestamp(
        int(timestamp_ms) / 1000,
        timezone.utc,
    ).replace(tzinfo=None)


def _final_candles(candles):
    return [
        candle
        for candle in candles
        if (
            candle.get("is_final", True)
            if isinstance(candle, dict)
            else getattr(candle, "is_final", True)
        )
    ]
