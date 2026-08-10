from contextlib import asynccontextmanager
import secrets
import time
import uuid

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
from app.observability.http_operations import SlidingWindowRateLimiter
from app.observability.http_operations import build_http_logger
from app.repositories.automation_settings_repository import ensure_automation_settings_schema
from app.repositories.trade_thesis_repository import ensure_trade_thesis_lineage_schema


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.validate_runtime()
    active_scheduler = None
    live_market_started = False

    print("QuantPulse Starting")

    if settings.environment == "development":
        ensure_automation_settings_schema(db_engine)

    ensure_trade_thesis_lineage_schema(db_engine)

    if USING_SQLITE_FALLBACK:
        bootstrap_sqlite_demo_data(db_engine)
        print("SQLite fallback seeded")

    if settings.run_scheduler:
        try:
            from app.scheduler import scheduler as scheduler_module
            from app.scheduler.scheduler import start_scheduler
        except ModuleNotFoundError as exc:
            print(f"Scheduler disabled: missing dependency {exc.name}")
        else:
            if start_scheduler():
                active_scheduler = scheduler_module.get_scheduler()

    if settings.run_live_market:
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
rate_limiter = SlidingWindowRateLimiter()
http_logger = build_http_logger()

ALLOWED_ORIGINS = set(settings.allowed_origins)

app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(ALLOWED_ORIGINS),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def ensure_cors_headers(request: Request, call_next):
    started_at = time.perf_counter()
    origin = request.headers.get("origin")
    request_id = _request_id(request)
    request.state.request_id = request_id
    mutating = request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}

    if _rate_limit_exceeded(request, mutating):
        response = JSONResponse(
            {"detail": "Rate limit exceeded"},
            status_code=429,
            headers={"Retry-After": "60"},
        )
    elif mutating and settings.require_admin_auth:
        supplied_key = _admin_api_key_from_request(request)
        if not supplied_key or not secrets.compare_digest(supplied_key, settings.admin_api_key):
            response = JSONResponse(
                {"detail": "Administrator authentication required"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        else:
            response = await _call_with_error_boundary(request, call_next)
    else:
        response = await _call_with_error_boundary(request, call_next)

    if origin in ALLOWED_ORIGINS:
        response.headers.setdefault("Access-Control-Allow-Origin", origin)
        response.headers.setdefault("Access-Control-Allow-Credentials", "true")
        response.headers.setdefault("Vary", "Origin")

    _apply_security_headers(response, request_id)
    duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
    http_logger.info(
        "http_request",
        extra={
            "structured": {
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
                "client": _client_identifier(request),
            }
        },
    )

    return response


async def _call_with_error_boundary(request, call_next):
    try:
        return await call_next(request)
    except Exception:
        http_logger.exception(
            "unhandled_request_exception",
            extra={
                "structured": {
                    "request_id": getattr(request.state, "request_id", None),
                    "method": request.method,
                    "path": request.url.path,
                }
            },
        )
        return JSONResponse({"detail": "Internal Server Error"}, status_code=500)


def _admin_api_key_from_request(request):
    authorization = request.headers.get("authorization", "")
    scheme, _, credential = authorization.partition(" ")
    if scheme.lower() == "bearer" and credential:
        return credential.strip()
    return request.headers.get("x-quantpulse-admin-key", "").strip()


def _rate_limit_exceeded(request, mutating):
    if not getattr(settings, "rate_limit_enabled", False):
        return False
    if request.url.path in {"/health/live", "/health/ready"}:
        return False
    limit = (
        getattr(settings, "admin_rate_limit_per_minute", 30)
        if mutating
        else getattr(settings, "rate_limit_per_minute", 120)
    )
    bucket = "admin" if mutating else "read"
    key = f"{_client_identifier(request)}:{bucket}"
    return not rate_limiter.allow(key, limit, window_seconds=60)


def _client_identifier(request):
    if getattr(settings, "trust_proxy_headers", False):
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",", 1)[0].strip()[:64]
    return (request.client.host if request.client else "unknown")[:64]


def _request_id(request):
    supplied = request.headers.get("x-request-id", "").strip()
    if supplied and len(supplied) <= 128 and all(
        character.isalnum() or character in "-_." for character in supplied
    ):
        return supplied
    return uuid.uuid4().hex


def _apply_security_headers(response, request_id):
    response.headers.setdefault("X-Request-ID", request_id)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=()",
    )
    if getattr(settings, "environment", "development") == "production":
        response.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains",
        )
    if response.headers.get("content-type", "").startswith("application/json"):
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'none'; frame-ancestors 'none'",
        )

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
