from fastapi import APIRouter

from app.config import get_settings
from app.database.sqlserver import DATABASE_URL


router = APIRouter(prefix="/health", tags=["Health"])


@router.get("")
async def health():
    settings = get_settings()

    return {
        "system": settings.app_name,
        "version": settings.version,
        "environment": settings.environment,
        "status": "running",
        "scheduler_enabled": settings.start_scheduler,
    }


@router.get("/dependencies")
async def dependency_check():
    return {
        "database_configured": bool(DATABASE_URL),
        "database_url_scheme": DATABASE_URL.split("://", 1)[0] if "://" in DATABASE_URL else "unknown",
    }
