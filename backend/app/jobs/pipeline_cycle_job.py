from app.jobs.paper_trade_execute_job import run_paper_trade_execute_job
from app.jobs.paper_trade_monitor_job import run_paper_trade_monitor_job
from app.jobs.risk_job import run_risk_job
from app.jobs.watchlist_persist_job import run_watchlist_persist_job


def run_pipeline_cycle_job():
    results = {
        "watchlist_persist": run_watchlist_persist_job(),
        "risk": run_risk_job(),
        "paper_trade_execute": run_paper_trade_execute_job(),
        "paper_trade_monitor": run_paper_trade_monitor_job(),
    }

    return {
        "source": "pipeline_cycle",
        "status": "COMPLETED",
        "order": [
            "watchlist_persist",
            "risk",
            "paper_trade_execute",
            "paper_trade_monitor",
        ],
        "results": results,
    }
