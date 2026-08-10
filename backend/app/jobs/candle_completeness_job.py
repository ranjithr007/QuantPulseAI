"""Scheduled read-only candle completeness snapshot."""

import logging

from app.database.bootstrap import bootstrap_sqlite_demo_data
from app.database.sqlserver import SessionLocal
from app.database.sqlserver import USING_SQLITE_FALLBACK
from app.database.sqlserver import engine as db_engine
from app.observability.candle_completeness import (
    build_candle_completeness_report,
)
from app.observability.candle_completeness import (
    cache_candle_completeness_report,
)

logger = logging.getLogger(__name__)


def run_candle_completeness_job():
    _prepare_storage()
    db = SessionLocal()
    try:
        report = build_candle_completeness_report(db)
        cache_candle_completeness_report(report)
        if report.get("status") != "HEALTHY":
            logger.warning(
                "Candle completeness degraded: %s; temporal progress=%s%%",
                ", ".join(report.get("unhealthy_series") or []),
                (report.get("temporal_validation") or {}).get(
                    "progress_percent"
                ),
            )
        return report
    except Exception as exc:
        report = {
            "contract": "candle_completeness_monitor_v1",
            "status": "FAILED",
            "source": "canonical_final_candle_repository",
            "read_only": True,
            "reason": str(exc),
        }
        cache_candle_completeness_report(report)
        logger.exception("Candle completeness monitor failed")
        return report
    finally:
        db.close()


def _prepare_storage():
    if USING_SQLITE_FALLBACK:
        bootstrap_sqlite_demo_data(db_engine)
