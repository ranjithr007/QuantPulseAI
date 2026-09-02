"""Worker-owned daily Phase 2 evidence checkpoint."""

from datetime import datetime

from app.api.v1.paper_trade_api import record_phase2_evidence_checkpoint
from app.database.sqlserver import SessionLocal
from app.utils.network_resilience import summarize_network_error


def run_phase2_daily_checkpoint_job(*, context=None, now=None):
    """Create today's checkpoint once; subsequent pipeline cycles are no-ops."""
    del context
    observed_at = (now or datetime.utcnow()).replace(tzinfo=None)
    db = SessionLocal()

    try:
        result = record_phase2_evidence_checkpoint(
            db,
            checkpoint_date=observed_at.date().isoformat(),
            observed_at=observed_at,
        )
        return {
            "status": "OK",
            "source": "phase2_daily_checkpoint_job",
            "action": str(result.get("status") or "UNKNOWN").lower(),
            "checkpoint": result,
        }
    except Exception as exc:
        db.rollback()
        return {
            "status": "FAILED",
            "source": "phase2_daily_checkpoint_job",
            "action": "failed",
            "error": summarize_network_error(exc),
        }
    finally:
        db.close()
