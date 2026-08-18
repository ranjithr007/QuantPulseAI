"""Bounded recovery for missed Phase 2 opportunity evaluations.

The cloud worker does not run the Windows Phase 2 supervisor.  This job keeps
the official opportunity ledger complete inside the deterministic worker
pipeline while preserving point-in-time reconstruction and an audit trail.
"""

import json
from datetime import datetime, timedelta

from app.api.v1.paper_trade_api import PHASE2_OPPORTUNITY_DECISION_VERSION
from app.api.v1.paper_trade_api import PHASE2_RECOVERY_EVENT_CATEGORY
from app.api.v1.paper_trade_api import PHASE2_RECOVERY_EVENT_SOURCE
from app.api.v1.paper_trade_api import _phase2_opportunity_coverage
from app.api.v1.signals_api import _reconstruct_phase2_opportunity_snapshot
from app.database.sqlserver import SessionLocal
from app.repositories.data_quality_event_repository import DataQualityEventRepository
from app.repositories.point_in_time_snapshot_repository import list_decision_snapshots
from app.repositories.symbol_repository import SymbolRepository
from app.utils.network_resilience import summarize_network_error


RECOVERY_WINDOW_HOURS = 24
SCHEDULER_GRACE_MINUTES = 15
MAX_RECOVERY_EVALUATIONS = 48
RETRY_COOLDOWN_MINUTES = 30


def run_opportunity_coverage_recovery_job(*, context=None, now=None):
    """Recover a bounded set of missing closed-1h opportunity snapshots."""
    del context
    observed_at = (now or datetime.utcnow()).replace(tzinfo=None)
    created_after = observed_at - timedelta(hours=RECOVERY_WINDOW_HOURS)
    db = SessionLocal()
    event_repo = DataQualityEventRepository()

    try:
        expected_symbols = sorted(
            {
                item.symbol
                for item in SymbolRepository().get_active_symbols(db)
            }
        )
        records = _opportunity_records(db, created_after)
        coverage_before = _phase2_opportunity_coverage(
            records,
            expected_symbols,
            SCHEDULER_GRACE_MINUTES,
        )
        if coverage_before.get("status") == "NOT_STARTED" and expected_symbols:
            bootstrap_missing = _bootstrap_missing(expected_symbols, observed_at)
            coverage_before = {
                **coverage_before,
                "status": "GAPS_DETECTED",
                "expected_evaluations": sum(
                    len(item["symbols"]) for item in bootstrap_missing
                ),
                "missing_evaluations": sum(
                    len(item["symbols"]) for item in bootstrap_missing
                ),
                "missing": bootstrap_missing,
                "bootstrap_recovery": True,
            }
        if coverage_before.get("status") != "GAPS_DETECTED":
            return {
                "status": "OK",
                "source": "opportunity_coverage_recovery",
                "action": "not_required",
                "coverage": coverage_before,
            }

        missing = _bounded_missing(coverage_before.get("missing") or [])
        gap_signature = _gap_signature(missing)
        if _within_retry_cooldown(
            event_repo,
            db,
            gap_signature,
            observed_at,
        ):
            return {
                "status": "OK",
                "source": "opportunity_coverage_recovery",
                "action": "cooldown",
                "gap_signature": gap_signature,
                "coverage": coverage_before,
            }

        _record_event(
            event_repo,
            db,
            status="ATTEMPTED",
            reason="Bounded worker opportunity coverage recovery started.",
            gap_signature=gap_signature,
            missing_before=coverage_before.get("missing_evaluations"),
            observed_at=observed_at,
        )

        recovered = []
        for gap in missing:
            slot = gap["effective_timestamp"]
            for symbol in gap["symbols"]:
                recovered.append(
                    _reconstruct_phase2_opportunity_snapshot(db, symbol, slot)
                )

        coverage_after = _phase2_opportunity_coverage(
            _opportunity_records(db, created_after),
            expected_symbols,
            SCHEDULER_GRACE_MINUTES,
        )
        missing_after = int(coverage_after.get("missing_evaluations") or 0)
        outcome = "RECOVERED" if missing_after == 0 else "UNRESOLVED"
        _record_event(
            event_repo,
            db,
            status=outcome,
            reason=(
                "Worker opportunity coverage recovery completed."
                if outcome == "RECOVERED"
                else "Worker opportunity coverage recovery left unresolved evaluations."
            ),
            gap_signature=gap_signature,
            missing_before=coverage_before.get("missing_evaluations"),
            missing_after=missing_after,
            observed_at=observed_at,
        )
        return {
            "status": "OK" if outcome == "RECOVERED" else "DEGRADED",
            "source": "opportunity_coverage_recovery",
            "action": outcome.lower(),
            "gap_signature": gap_signature,
            "attempted_count": len(recovered),
            "persisted_count": sum(
                1 for item in recovered if item.get("persisted")
            ),
            "coverage_before": coverage_before,
            "coverage_after": coverage_after,
            "records": recovered,
        }
    except Exception as exc:
        error = summarize_network_error(exc)
        try:
            _record_event(
                event_repo,
                db,
                status="RETRY_FAILED",
                reason="Worker opportunity coverage recovery failed.",
                gap_signature=locals().get("gap_signature"),
                missing_before=(locals().get("coverage_before") or {}).get(
                    "missing_evaluations"
                ),
                observed_at=observed_at,
                error=error,
            )
        except Exception:
            db.rollback()
        return {
            "status": "DEGRADED",
            "source": "opportunity_coverage_recovery",
            "action": "retry_failed",
            "error": error,
        }
    finally:
        db.close()


def _opportunity_records(db, created_after):
    return list_decision_snapshots(
        db,
        decision_version=PHASE2_OPPORTUNITY_DECISION_VERSION,
        created_after=created_after,
        limit=100000,
    )


def _bounded_missing(missing):
    bounded = []
    remaining = MAX_RECOVERY_EVALUATIONS
    for gap in missing:
        if remaining <= 0:
            break
        symbols = sorted(set(gap.get("symbols") or []))[:remaining]
        if not symbols:
            continue
        bounded.append(
            {
                "effective_timestamp": gap.get("effective_timestamp"),
                "symbols": symbols,
                "missing_count": len(symbols),
            }
        )
        remaining -= len(symbols)
    return bounded


def _bootstrap_missing(expected_symbols, observed_at):
    """Build the complete rolling window when the ledger has no seed record."""
    grace_cutoff = observed_at - timedelta(minutes=SCHEDULER_GRACE_MINUTES)
    latest_slot = (
        grace_cutoff.replace(minute=0, second=0, microsecond=0)
        - timedelta(hours=1)
    )
    first_slot = latest_slot - timedelta(hours=RECOVERY_WINDOW_HOURS - 1)
    return [
        {
            "effective_timestamp": first_slot + timedelta(hours=offset),
            "symbols": list(expected_symbols),
            "missing_count": len(expected_symbols),
        }
        for offset in range(RECOVERY_WINDOW_HOURS)
    ]


def _gap_signature(missing):
    return json.dumps(missing, sort_keys=True, default=str, separators=(",", ":"))


def _within_retry_cooldown(event_repo, db, gap_signature, observed_at):
    threshold = observed_at - timedelta(minutes=RETRY_COOLDOWN_MINUTES)
    events = event_repo.list_events(
        db,
        source=PHASE2_RECOVERY_EVENT_SOURCE,
        category=PHASE2_RECOVERY_EVENT_CATEGORY,
        limit=20,
    )
    return any(
        (item.get("details") or {}).get("gap_signature") == gap_signature
        and item.get("status") in {"ATTEMPTED", "UNRESOLVED", "RETRY_FAILED"}
        and _event_timestamp(item) >= threshold
        for item in events
    )


def _event_timestamp(event):
    value = event.get("created_at") or event.get("observed_at")
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(
            tzinfo=None
        )
    except (TypeError, ValueError):
        return datetime.min


def _record_event(
    event_repo,
    db,
    *,
    status,
    reason,
    gap_signature,
    missing_before,
    observed_at,
    missing_after=None,
    error=None,
):
    blocked = status in {"UNRESOLVED", "RETRY_FAILED"}
    event_repo.record_events(
        db,
        [
            {
                "symbol": "SYSTEM",
                "timeframe": "1h",
                "source": PHASE2_RECOVERY_EVENT_SOURCE,
                "category": PHASE2_RECOVERY_EVENT_CATEGORY,
                "severity": "error" if blocked else "info" if status == "RECOVERED" else "warning",
                "status": status,
                "blocked": blocked,
                "reason": reason,
                "details": {
                    "gap_signature": gap_signature,
                    "missing_before": missing_before,
                    "missing_after": missing_after,
                    "repair_action": "point_in_time_final_candle_reconstruction",
                    "error": error,
                },
                "observed_at": observed_at,
                "effective_at": observed_at,
            }
        ],
    )
