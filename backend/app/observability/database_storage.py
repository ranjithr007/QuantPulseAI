"""Read-only PostgreSQL storage telemetry for capacity and retention decisions."""

from sqlalchemy import text


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
        with engine.connect() as connection:
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
