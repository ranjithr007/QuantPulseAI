from apscheduler.schedulers.background import BackgroundScheduler


from app.jobs.market_job import run_market_job
from app.jobs.intelligence_job import run_intelligence_job
from app.jobs.heatmap_job import run_heatmap_job
from app.jobs.whale_job import run_whale_job
from app.jobs.whale_intelligence_job import run_whale_intelligence_job
from app.jobs.master_ai_job import run_master_ai_job
from app.jobs.signal_quality_job import run_signal_quality_job
from app.jobs.backtest_job import run_backtest_job
from app.jobs.feature_jobs import run_feature_job
from app.jobs.regime_jobs import run_regime_job
from app.jobs.orderflow_jobs import run_orderflow_job
from app.jobs.smc_job import run_smc_job
from app.jobs.ml_dataset_job import run_ml_dataset_job
from app.jobs.ml_label_job import run_ml_label_job
from app.jobs.fusion_job import run_fusion_job
from app.jobs.trade_plan_job import run_trade_plan_job
from app.jobs.memory_job import run_memory_job
from app.jobs.risk_job import run_risk_job

scheduler = BackgroundScheduler(timezone="Asia/Kolkata", daemon=True)


def start_scheduler():

    if scheduler.running:

        print("Scheduler already running")

        return

    scheduler.remove_all_jobs()

    print("🚀 Starting QuantPulse Scheduler")

    scheduler.add_job(
        run_market_job,
        "interval",
        seconds=30,
        id="market",
        max_instances=1,
        replace_existing=True,
    )

    scheduler.add_job(
        run_whale_job,
        "interval",
        seconds=20,
        id="whales",
        max_instances=1,
        replace_existing=True,
    )

    scheduler.add_job(
        run_intelligence_job,
        "interval",
        seconds=30,
        id="intelligence",
        max_instances=1,
        replace_existing=True,
    )

    scheduler.add_job(
        run_heatmap_job,
        "interval",
        seconds=40,
        id="heatmap",
        max_instances=1,
        replace_existing=True,
    )

    scheduler.add_job(
        run_whale_intelligence_job,
        "interval",
        seconds=50,
        id="whale_ai",
        max_instances=1,
        replace_existing=True,
    )

    scheduler.add_job(
        run_master_ai_job,
        "interval",
        seconds=60,
        id="master_ai",
        max_instances=1,
        replace_existing=True,
    )
    scheduler.add_job(
        run_signal_quality_job,
        "interval",
        seconds=90,
        id="quality",
        max_instances=1,
        replace_existing=True,
    )
    scheduler.add_job(
        run_backtest_job,
        "interval",
        minutes=1,
        id="backtest",
        max_instances=1,
        replace_existing=True,
    )
    scheduler.add_job(
        run_feature_job,
        "interval",
        minutes=1,
        id="feature",
        max_instances=1,
        replace_existing=True,
    )
    scheduler.add_job(
        run_regime_job,
        "interval",
        minutes=1,
        id="regime",
        max_instances=1,
        replace_existing=True,
    )
    scheduler.add_job(
        run_orderflow_job,
        "interval",
        minutes=1,
        id="orderflow",
        max_instances=1,
        replace_existing=True,
    )
    scheduler.add_job(
        run_smc_job,
        "interval",
        minutes=1,
        id="smcengin",
        max_instances=1,
        replace_existing=True,
    )
    scheduler.add_job(
        run_ml_dataset_job,
        "interval",
        minutes=15,
        id="ml_dataset_job",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        run_ml_label_job,
        "interval",
        minutes=5,
        id="ml_label_job",
        replace_existing=True,
    )
    scheduler.add_job(
        run_fusion_job,
        trigger="interval",
        seconds=60,
        id="fusion_ai_job",
        max_instances=1,
        replace_existing=True,
    )
    scheduler.add_job(
        run_trade_plan_job,
        trigger="interval",
        seconds=120,
        id="trade_plan_job",
        max_instances=1,
        replace_existing=True,
    )
    scheduler.add_job(
        run_memory_job,
        trigger="interval",
        minutes=5,
        id="ai_memory_job",
        max_instances=1,
        replace_existing=True,
    )
    scheduler.add_job(
        run_risk_job,
        "interval",
        minutes=1,
        id="risk_job",
        max_instances=2,
        replace_existing=True,
    )
    scheduler.start()