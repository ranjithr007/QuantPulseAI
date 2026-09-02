from datetime import datetime, timezone

from app.database.sqlserver import SessionLocal, USING_SQLITE_FALLBACK
from app.jobs.paper_trade_execute_job import run_paper_trade_execute_job
from app.jobs.paper_trade_monitor_job import run_paper_trade_monitor_job
from app.jobs.risk_job import run_risk_job
from app.jobs.watchlist_persist_job import run_watchlist_persist_job
from app.repositories.pipeline_run_repository import PipelineRunRepository
from app.utils.network_resilience import summarize_network_error


STALE_PIPELINE_AFTER_SECONDS = 1800


def run_pipeline_cycle_job():
    results = {}
    ledger_db = None
    pipeline_record = None
    ledger = PipelineRunRepository()
    generation_id = "pipeline-cycle-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")

    if not USING_SQLITE_FALLBACK:
        try:
            ledger_db = SessionLocal()
            results["ledger_recovery"] = ledger.recover_stale_running(
                ledger_db,
                stale_after_seconds=STALE_PIPELINE_AFTER_SECONDS,
            )
            pipeline_record, _ = ledger.start_pipeline(
                ledger_db,
                generation_id,
                source_cutoff=datetime.utcnow(),
                metadata={"cycle": "paper_execution", "stages": 4},
            )
        except Exception as exc:
            if ledger_db is not None:
                ledger_db.rollback()
                ledger_db.close()
                ledger_db = None
            print(f"Pipeline ledger unavailable: {summarize_network_error(exc)}")

    try:
        for name, job in [
            ("paper_trade_monitor", run_paper_trade_monitor_job),
            ("watchlist_persist", run_watchlist_persist_job),
            ("risk", run_risk_job),
            ("paper_trade_execute", run_paper_trade_execute_job),
        ]:
            job_record = None
            if ledger_db is not None and pipeline_record is not None:
                try:
                    job_record, _ = ledger.start_job(
                        ledger_db,
                        pipeline_record.id,
                        name,
                        idempotency_key=f"{generation_id}:{name}",
                        input_generation_id=generation_id,
                    )
                except Exception as exc:
                    print(f"Pipeline job ledger unavailable for {name}: {summarize_network_error(exc)}")
            try:
                results[name] = job()
                if job_record is not None:
                    ledger.finish_job(
                        ledger_db,
                        job_record.id,
                        status="COMPLETED",
                        rows_written=_rows_written(results[name]),
                        output_generation_id=generation_id,
                    )
            except Exception as ex:
                results[name] = {"status": "FAILED", "error": summarize_network_error(ex)}
                if job_record is not None:
                    ledger.finish_job(
                        ledger_db,
                        job_record.id,
                        status="FAILED",
                        error_category=type(ex).__name__,
                        error_message=summarize_network_error(ex),
                        output_generation_id=generation_id,
                    )

        status = _pipeline_cycle_status(results)

        if pipeline_record is not None and ledger_db is not None:
            ledger.finish_pipeline(ledger_db, pipeline_record.id, status=status)

        return {
            "source": "pipeline_cycle",
            "generation_id": generation_id,
            "pipeline_run_id": getattr(pipeline_record, "id", None),
            "status": status,
            "order": [
                "paper_trade_monitor",
                "watchlist_persist",
                "risk",
                "paper_trade_execute",
            ],
            "results": results,
        }
    finally:
        if ledger_db is not None:
            ledger_db.close()


def _rows_written(result):
    if not isinstance(result, dict):
        return 0
    for key in ("rows_written", "saved", "inserted", "count"):
        value = result.get(key)
        if isinstance(value, int):
            return value
    return 0


def _pipeline_cycle_status(results):
    statuses = [str(item.get("status") or "").upper() for item in (results or {}).values()]
    if not statuses or any(status == "FAILED" for status in statuses):
        if all(status == "FAILED" for status in statuses if status):
            return "FAILED"
        return "PARTIAL"
    return "COMPLETED"
