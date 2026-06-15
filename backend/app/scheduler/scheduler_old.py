from apscheduler.schedulers.background import BackgroundScheduler

from app.jobs.market_job import run_market_job
from app.jobs.derivative_job import run_derivative_job
from app.jobs.intelligence_job import run_intelligence_job
from app.jobs.liquidation_job import run_liquidation_job
from app.jobs.heatmap_job import run_heatmap_job
from app.jobs.ai_signal_job import run_ai_signal_job
from app.jobs.whale_job import run_whale_job
from app.jobs.whale_intelligence_job import run_whale_intelligence_job
from app.jobs.master_ai_job import run_master_ai_job


scheduler = BackgroundScheduler(daemon=True)


def start_scheduler_old():
    if scheduler.running:
        print("Scheduler already running")
        return
    scheduler.remove_all_jobs()
    print("Starting QuantPulse Scheduler")

    scheduler.add_job(run_market_job, "interval", seconds=30)
    scheduler.add_job(run_derivative_job, "interval", seconds=60)
    scheduler.add_job(run_intelligence_job, "interval", seconds=30)
    scheduler.add_job(run_liquidation_job, "date")
    scheduler.add_job(run_heatmap_job, "interval", seconds=60)
    scheduler.add_job(run_ai_signal_job, "interval", seconds=30)
    scheduler.add_job(run_whale_job, "interval", seconds=30)
    scheduler.add_job(
        run_whale_intelligence_job, "interval", minutes=1, max_instances=1
    )
    scheduler.add_job(run_master_ai_job, "interval", minutes=1, max_instances=1)
    scheduler.start()

    print("QuantPulse Scheduler Started")