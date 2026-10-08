"""Read-only PostgreSQL storage telemetry for capacity and retention decisions.

Storage telemetry is intentionally isolated from the application pool.  The
endpoint is used while diagnosing database pressure, so waiting behind the
same exhausted pool would hide the useful result behind a QueuePool timeout.
"""

from threading import Lock

from sqlalchemy import create_engine
from sqlalchemy import text
from sqlalchemy.pool import NullPool


PROTECTED_EVIDENCE_TABLES = {
    "MarketFeatures",
    "MarketOrderFlow",
    "MarketRegimes",
    "ai_signals",
    "decision_snapshots",
    "feature_snapshots",
    "funding_rates",
    "futures_margin_brackets",
    "futures_mark_prices",
    "liquidation_heatmaps",
    "liquidations",
    "market_candles",
    "orderbook_snapshots",
    "paper_trades",
    "risk_decisions",
    "spot_market_candles",
    "strategy_shadow_trades",
    "thesis_snapshots",
    "trade_plans",
    "whale_signals",
    "whale_trades",
}
OPERATIONAL_RETENTION_TABLES = {"pipeline_runs", "pipeline_job_runs"}

_TELEMETRY_ENGINE = None
_TELEMETRY_URL = None
_TELEMETRY_LOCK = Lock()


def _telemetry_engine(engine):
    """Return a short-lived connection engine separate from the app pool.

    The fake engine used by unit tests and non-PostgreSQL backends do not carry
    a renderable SQLAlchemy URL, so they continue using their supplied engine.
    """

    global _TELEMETRY_ENGINE, _TELEMETRY_URL
    url = getattr(engine, "url", None)
    render_url = getattr(url, "render_as_string", None)
    if not callable(render_url):
        return engine

    url_text = render_url(hide_password=False)
    if _TELEMETRY_ENGINE is not None and _TELEMETRY_URL == url_text:
        return _TELEMETRY_ENGINE

    with _TELEMETRY_LOCK:
        if _TELEMETRY_ENGINE is None or _TELEMETRY_URL != url_text:
            if _TELEMETRY_ENGINE is not None:
                _TELEMETRY_ENGINE.dispose()
            _TELEMETRY_ENGINE = create_engine(
                url_text,
                poolclass=NullPool,
                pool_pre_ping=True,
                connect_args={
                    "options": "-c statement_timeout=5000 -c lock_timeout=2000",
                },
            )
            _TELEMETRY_URL = url_text
    return _TELEMETRY_ENGINE


def build_database_storage_report(engine, settings, *, table_limit=25):
    backend = engine.url.get_backend_name()
    retention = {
        "enabled": bool(settings.pipeline_retention_enabled),
        "days": int(settings.pipeline_retention_days),
        "batch_size": int(settings.pipeline_retention_batch_size),
        "tables": sorted(OPERATIONAL_RETENTION_TABLES),
        "protected_evidence_deleted": False,
    }
    if backend != "postgresql":
        return {
            "source": "database_storage",
            "status": "UNAVAILABLE",
            "backend": backend,
            "reason": "PostgreSQL storage statistics are unavailable for this backend",
            "retention": retention,
            "tables": [],
        }

    limit = max(1, min(100, int(table_limit)))
    try:
        # Do not consume a slot from the already-busy application QueuePool.
        # PostgreSQL statistics are read through a direct, non-pooled session.
        with _telemetry_engine(engine).connect() as connection:
            database_bytes = int(
                connection.execute(
                    text("SELECT pg_database_size(current_database())")
                ).scalar()
                or 0
            )
            rows = connection.execute(
                text(
                    """
                    SELECT
                        relname AS table_name,
                        pg_total_relation_size(relid)::bigint AS total_bytes,
                        pg_relation_size(relid)::bigint AS table_bytes,
                        pg_indexes_size(relid)::bigint AS index_bytes,
                        n_live_tup::bigint AS estimated_rows,
                        n_dead_tup::bigint AS dead_rows
                    FROM pg_stat_user_tables
                    WHERE schemaname = 'public'
                    ORDER BY pg_total_relation_size(relid) DESC
                    LIMIT :table_limit
                    """
                ),
                {"table_limit": limit},
            ).mappings().all()
    except Exception as exc:
        return {
            "source": "database_storage",
            "status": "FAILED",
            "backend": backend,
            "reason": f"{type(exc).__name__}: {str(exc).splitlines()[0]}",
            "retention": retention,
            "tables": [],
        }

    tables = [_table_record(row) for row in rows]
    return {
        "source": "database_storage",
        "status": "AVAILABLE",
        "backend": backend,
        "database_bytes": database_bytes,
        "database_size": _human_bytes(database_bytes),
        "reported_table_count": len(tables),
        "retention": retention,
        "tables": tables,
    }


def _table_record(row):
    table_name = str(row["table_name"])
    total_bytes = int(row.get("total_bytes") or 0)
    estimated_rows = int(row.get("estimated_rows") or 0)
    dead_rows = int(row.get("dead_rows") or 0)
    observed_rows = max(0, estimated_rows + dead_rows)
    return {
        "table": table_name,
        "classification": (
            "PROTECTED_BACKTEST_EVIDENCE"
            if table_name in PROTECTED_EVIDENCE_TABLES
            else "OPERATIONAL_RETENTION"
            if table_name in OPERATIONAL_RETENTION_TABLES
            else "UNCLASSIFIED"
        ),
        "total_bytes": total_bytes,
        "total_size": _human_bytes(total_bytes),
        "table_bytes": int(row.get("table_bytes") or 0),
        "index_bytes": int(row.get("index_bytes") or 0),
        "estimated_rows": estimated_rows,
        "dead_rows": dead_rows,
        "dead_row_percent": (
            round(dead_rows / observed_rows * 100, 2) if observed_rows else 0.0
        ),
    }


def _human_bytes(value):
    size = float(max(0, int(value or 0)))
    units = ("B", "KB", "MB", "GB", "TB")
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.2f} {unit}"
        size /= 1024
