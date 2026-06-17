from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1 import backtest_api
from app.api.v1 import dataset_api
from app.api.v1 import features_api
from app.api.v1 import health_api
from app.api.v1 import ai_scores_api
from app.api.v1 import indicators_api
from app.api.v1 import intelligence_api
from app.api.v1 import market_api
from app.api.v1 import master_ai_api
from app.api.v1 import ml_api
from app.api.v1 import ml_label_api
from app.api.v1 import orderflow_api
from app.api.v1 import paper_trade_api
from app.api.v1 import pipeline_api
from app.api.v1 import prediction_api
from app.api.v1 import regime_api
from app.api.v1 import risk_api
from app.api.v1 import scheduler_api
from app.api.v1 import signals_api
from app.api.v1 import smc_api
from app.api.v1 import symbols_api
from app.api.v1 import trade_plan_api
from app.api.v2 import fusion_ai_api
from app.api.v2 import master_ai_v2_api
from app.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    active_scheduler = None

    print("QuantPulse Starting")

    if settings.start_scheduler:
        try:
            from app.scheduler import scheduler as scheduler_module
            from app.scheduler.scheduler import start_scheduler
        except ModuleNotFoundError as exc:
            print(f"Scheduler disabled: missing dependency {exc.name}")
        else:
            if start_scheduler():
                active_scheduler = scheduler_module.get_scheduler()

    yield

    print("QuantPulse stopping")

    if active_scheduler and active_scheduler.running:
        active_scheduler.shutdown(wait=False)


settings = get_settings()
app = FastAPI(title=f"{settings.app_name} v{settings.version}", lifespan=lifespan)

app.include_router(health_api.router)
app.include_router(market_api.router)
app.include_router(features_api.router)
app.include_router(regime_api.router)
app.include_router(orderflow_api.router)
app.include_router(smc_api.router)
app.include_router(ai_scores_api.router)
app.include_router(indicators_api.router)
app.include_router(intelligence_api.router)
app.include_router(master_ai_api.router)
app.include_router(master_ai_v2_api.router)
app.include_router(fusion_ai_api.router)
app.include_router(backtest_api.router)
app.include_router(ml_api.router)
app.include_router(dataset_api.router)
app.include_router(ml_label_api.router)
app.include_router(prediction_api.router)
app.include_router(risk_api.router)
app.include_router(scheduler_api.router)
app.include_router(signals_api.router)
app.include_router(symbols_api.router)
app.include_router(trade_plan_api.router)
app.include_router(paper_trade_api.router)
app.include_router(pipeline_api.router)


@app.get("/")
def root():
    return {
        "system": settings.app_name,
        "version": settings.version,
        "status": "running",
        "health_url": "/health",
    }
