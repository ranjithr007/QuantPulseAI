from contextlib import asynccontextmanager
from traceback import format_exc

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.requests import Request

from app.api.v1 import backtest_api
from app.api.v1 import automation_api
from app.api.v1 import dataset_api
from app.api.v1 import derivatives_api
from app.api.v1 import features_api
from app.api.v1 import health_api
from app.api.v1 import ai_scores_api
from app.api.v1 import indicators_api
from app.api.v1 import intelligence_api
from app.api.v1 import live_market_api
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
from app.api.v1 import thesis_api
from app.api.v1 import trade_plan_api
from app.api.v2 import fusion_ai_api
from app.api.v2 import master_ai_v2_api
from app.config import get_settings
from app.database.bootstrap import bootstrap_sqlite_demo_data
from app.database.sqlserver import USING_SQLITE_FALLBACK
from app.database.sqlserver import engine as db_engine
from app.repositories.automation_settings_repository import ensure_automation_settings_schema
from app.repositories.trade_thesis_repository import ensure_trade_thesis_lineage_schema


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    active_scheduler = None
    live_market_started = False

    print("QuantPulse Starting")

    if settings.environment == "development":
        ensure_automation_settings_schema(db_engine)

    ensure_trade_thesis_lineage_schema(db_engine)

    if USING_SQLITE_FALLBACK:
        bootstrap_sqlite_demo_data(db_engine)
        print("SQLite fallback seeded")

    if settings.start_scheduler:
        try:
            from app.scheduler import scheduler as scheduler_module
            from app.scheduler.scheduler import start_scheduler
        except ModuleNotFoundError as exc:
            print(f"Scheduler disabled: missing dependency {exc.name}")
        else:
            if start_scheduler():
                active_scheduler = scheduler_module.get_scheduler()

    if settings.start_live_market:
        try:
            from app.services.live_market_service import start_live_market_listener
        except ModuleNotFoundError as exc:
            print(f"Live market disabled: missing dependency {exc.name}")
        else:
            live_market_started = start_live_market_listener(settings.live_market_symbols)

    yield

    print("QuantPulse stopping")

    if live_market_started:
        from app.services.live_market_service import stop_live_market_listener

        await stop_live_market_listener()

    if active_scheduler and active_scheduler.running:
        active_scheduler.shutdown(wait=False)


settings = get_settings()
app = FastAPI(title=f"{settings.app_name} v{settings.version}", lifespan=lifespan)

ALLOWED_ORIGINS = {
    "http://127.0.0.1:4173",
    "http://localhost:4173",
    *{f"http://127.0.0.1:{port}" for port in range(5173, 5180)},
    *{f"http://localhost:{port}" for port in range(5173, 5180)},
}

app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(ALLOWED_ORIGINS),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def ensure_cors_headers(request: Request, call_next):
    origin = request.headers.get("origin")

    try:
        response = await call_next(request)
    except Exception:
        print(format_exc())
        response = JSONResponse({"detail": "Internal Server Error"}, status_code=500)

    if origin in ALLOWED_ORIGINS:
        response.headers.setdefault("Access-Control-Allow-Origin", origin)
        response.headers.setdefault("Access-Control-Allow-Credentials", "true")
        response.headers.setdefault("Vary", "Origin")

    return response

app.include_router(health_api.router)
app.include_router(automation_api.router)
app.include_router(derivatives_api.router)
app.include_router(market_api.router)
app.include_router(features_api.router)
app.include_router(regime_api.router)
app.include_router(orderflow_api.router)
app.include_router(smc_api.router)
app.include_router(ai_scores_api.router)
app.include_router(indicators_api.router)
app.include_router(intelligence_api.router)
app.include_router(live_market_api.router)
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
app.include_router(thesis_api.router)
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
