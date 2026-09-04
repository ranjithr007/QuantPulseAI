"""Scheduled paper-only strategy evaluation and challenger generation."""

from app.database.sqlserver import SessionLocal
from app.strategies.learning import evaluate_due_strategy_versions


def run_strategy_learning_job():
    db = SessionLocal()
    try:
        return evaluate_due_strategy_versions(db)
    except Exception as exc:
        db.rollback()
        return {
            "status": "UNAVAILABLE",
            "reason": str(exc),
            "evaluated_count": 0,
            "created_candidate_count": 0,
            "live_execution_enabled": False,
        }
    finally:
        db.close()
