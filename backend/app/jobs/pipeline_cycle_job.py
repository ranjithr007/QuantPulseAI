from app.jobs.paper_trade_execute_job import run_paper_trade_execute_job
from app.jobs.paper_trade_monitor_job import run_paper_trade_monitor_job
from app.jobs.risk_job import run_risk_job
from app.jobs.watchlist_persist_job import run_watchlist_persist_job
from app.utils.network_resilience import summarize_network_error


def run_pipeline_cycle_job():
    results = {}

    for name, job in [
        ("watchlist_persist", run_watchlist_persist_job),
        ("risk", run_risk_job),
        ("paper_trade_execute", run_paper_trade_execute_job),
        ("paper_trade_monitor", run_paper_trade_monitor_job),
    ]:
        try:
            results[name] = job()
        except Exception as ex:
            results[name] = {"status": "FAILED", "error": summarize_network_error(ex)}

    status = _pipeline_cycle_status(results)

    return {
        "source": "pipeline_cycle",
        "status": status,
        "order": [
            "watchlist_persist",
            "risk",
            "paper_trade_execute",
            "paper_trade_monitor",
        ],
        "results": results,
    }


def _pipeline_cycle_status(results):
    statuses = [str(item.get("status") or "").upper() for item in (results or {}).values()]
    if not statuses or any(status == "FAILED" for status in statuses):
        if all(status == "FAILED" for status in statuses if status):
            return "FAILED"
        return "PARTIAL"
    return "COMPLETED"
