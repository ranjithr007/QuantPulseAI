"""Dependency-aware paper pipeline cycle.

The existing interval jobs remain available for compatibility, but this entry
point is the R2 reference order.  A failed required stage blocks downstream
execution. Optional strategy branches are recorded as failed without blocking
independent strategies that do not consume that branch.
"""

from datetime import datetime, timezone

from app.database.sqlserver import SessionLocal, USING_SQLITE_FALLBACK
from app.jobs.feature_jobs import run_feature_job
from app.jobs.fusion_job import run_fusion_job
from app.jobs.market_job import run_market_job
from app.jobs.market_participation_trend_job import run_market_participation_trend_job
from app.jobs.opportunity_coverage_recovery_job import run_opportunity_coverage_recovery_job
from app.jobs.orderflow_jobs import run_orderflow_job
from app.jobs.paper_trade_execute_job import run_paper_trade_execute_job
from app.jobs.paper_trade_monitor_job import run_paper_trade_monitor_job
from app.jobs.regime_jobs import run_regime_job
from app.jobs.risk_job import run_risk_job
from app.jobs.smc_job import run_smc_job
from app.jobs.watchlist_persist_job import run_watchlist_persist_job
from app.repositories.pipeline_run_repository import PipelineRunRepository
from app.pipeline.context import PipelineContext
from app.utils.network_resilience import summarize_network_error


STAGE_ORDER = (
    ("market", run_market_job),
    ("paper_trade_monitor", run_paper_trade_monitor_job),
    ("feature", run_feature_job),
    ("regime", run_regime_job),
    ("orderflow", run_orderflow_job),
    ("smc", run_smc_job),
    ("fusion", run_fusion_job),
    ("market_participation_trend", run_market_participation_trend_job),
    ("watchlist_persist", run_watchlist_persist_job),
    ("opportunity_coverage_recovery", run_opportunity_coverage_recovery_job),
    ("risk", run_risk_job),
    ("paper_trade_execute", run_paper_trade_execute_job),
)
ALWAYS_RUN_SAFETY_STAGES = frozenset(
    {"paper_trade_monitor", "opportunity_coverage_recovery"}
)
# These stages provide evidence to one or more strategies, but no individual
# branch is globally authoritative. A failure must be recorded as degradation
# while later independent branches and the risk refresh are still attempted.
# Candidate-level gates remain responsible for rejecting any strategy whose
# own required evidence is missing, stale, contradictory, or incomplete.
NON_BLOCKING_STRATEGY_STAGES = frozenset(
    {
        "market",
        "feature",
        "regime",
        "orderflow",
        "smc",
        "fusion",
        "market_participation_trend",
        "watchlist_persist",
        "opportunity_coverage_recovery",
    }
)
STALE_PIPELINE_AFTER_SECONDS = 1800


def run_deterministic_pipeline_job():
    generation_id = "deterministic-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    context = PipelineContext(
        generation_id=generation_id,
        source_cutoff=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    results = {}
    blocked = False
    degraded_stages = []
    ledger_db = None
    pipeline_record = None
    ledger = PipelineRunRepository()

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
                source_cutoff=context.source_cutoff,
                metadata={"cycle": "deterministic", "stage_order": [name for name, _ in STAGE_ORDER]},
            )
        except Exception as exc:
            if ledger_db is not None:
                ledger_db.rollback()
                ledger_db.close()
                ledger_db = None
            results["ledger"] = {"status": "UNAVAILABLE", "error": summarize_network_error(exc)}

    try:
        for name, job in STAGE_ORDER:
            if blocked and name not in ALWAYS_RUN_SAFETY_STAGES:
                results[name] = {"status": "BLOCKED", "reason": "UPSTREAM_STAGE_FAILED"}
                continue

            job_record = None
            if ledger_db is not None and pipeline_record is not None:
                job_record, _ = ledger.start_job(
                    ledger_db,
                    pipeline_record.id,
                    name,
                    idempotency_key=f"{generation_id}:{name}",
                    input_generation_id=generation_id,
                )

            try:
                if name == "paper_trade_execute" and not _execution_ready(results):
                    blocked = True
                    results[name] = {
                        "status": "BLOCKED",
                        "reason": "REQUIRED_PIPELINE_STAGES_INCOMPLETE",
                    }
                    if job_record is not None:
                        ledger.finish_job(
                            ledger_db,
                            job_record.id,
                            status="BLOCKED",
                            output_generation_id=generation_id,
                            error_category="REQUIRED_STAGES_INCOMPLETE",
                        )
                    continue
                result = _invoke_stage(job, context)
                stage_failed = _failed(result)
                if stage_failed:
                    is_blocking_failure = name not in NON_BLOCKING_STRATEGY_STAGES
                    blocked = blocked or is_blocking_failure
                    if not is_blocking_failure:
                        degraded_stages.append(name)
                    result = {
                        "status": "FAILED",
                        "blocking": is_blocking_failure,
                        "result": result,
                    }
                results[name] = result
                if job_record is not None:
                    ledger.finish_job(
                        ledger_db,
                        job_record.id,
                        status="FAILED" if stage_failed else "COMPLETED",
                        rows_written=_rows_written(result),
                        output_generation_id=generation_id,
                        error_category=(
                            "UPSTREAM_STAGE_FAILED"
                            if stage_failed and name not in NON_BLOCKING_STRATEGY_STAGES
                            else "OPTIONAL_STRATEGY_STAGE_FAILED"
                            if stage_failed
                            else None
                        ),
                    )
            except Exception as exc:
                is_blocking_failure = name not in NON_BLOCKING_STRATEGY_STAGES
                blocked = blocked or is_blocking_failure
                if not is_blocking_failure:
                    degraded_stages.append(name)
                results[name] = {
                    "status": "FAILED",
                    "blocking": is_blocking_failure,
                    "error": summarize_network_error(exc),
                }
                if job_record is not None:
                    ledger.finish_job(
                        ledger_db,
                        job_record.id,
                        status="FAILED",
                        output_generation_id=generation_id,
                        error_category=type(exc).__name__,
                        error_message=summarize_network_error(exc),
                    )

        status = (
            "FAILED"
            if blocked
            else "DEGRADED"
            if degraded_stages
            else "COMPLETED"
        )
        if pipeline_record is not None and ledger_db is not None:
            ledger.finish_pipeline(ledger_db, pipeline_record.id, status=status)
        return {
            "source": "deterministic_pipeline",
            "generation_id": generation_id,
            "pipeline_run_id": getattr(pipeline_record, "id", None),
            "status": status,
            "degraded_stages": degraded_stages,
            "order": [name for name, _ in STAGE_ORDER],
            "results": results,
        }
    finally:
        if ledger_db is not None:
            ledger_db.close()


def _failed(result):
    if not isinstance(result, dict):
        return False
    return str(result.get("status") or "").upper() in {"FAILED", "ERROR"}


def _rows_written(result):
    if not isinstance(result, dict):
        return len(result) if isinstance(result, list) else 0
    for key in ("rows_written", "saved", "inserted", "count"):
        value = result.get(key)
        if isinstance(value, int):
            return value
    return 0


def _execution_ready(results):
    # Entry execution has two global hard prerequisites: existing positions
    # must have been monitored successfully and each plan must have a current
    # risk decision. Evidence-engine failures are strategy-local and are
    # enforced by build_paper_trade_candidates against the exact strategy
    # contract instead of stopping unrelated strategies globally.
    required = ("paper_trade_monitor", "risk")
    for name in required:
        result = results.get(name)
        if result is None:
            return False
        if isinstance(result, dict):
            stage_status = str(result.get("status") or "").upper()
            if stage_status in {"FAILED", "ERROR", "BLOCKED"}:
                return False
            if result.get("errors") and not (
                name == "risk" and stage_status == "DEGRADED"
            ):
                return False
            continue
        if isinstance(result, list):
            if not result:
                return False
            for item in result:
                if not isinstance(item, dict):
                    continue
                if str(item.get("status") or "").upper() in {"FAILED", "ERROR", "BLOCKED"}:
                    return False
                if item.get("errors"):
                    return False
            continue
        # A scalar stage result cannot establish successful lineage.
        return False
    return all(name in results for name in required)


def _invoke_stage(job, context):
    """Call lineage-aware jobs while keeping old scheduler/test callables valid."""
    try:
        return job(context=context)
    except TypeError as exc:
        if "unexpected keyword argument 'context'" not in str(exc):
            raise
        return job()
