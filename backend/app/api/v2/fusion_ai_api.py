from fastapi import APIRouter, Query

from app.database.sqlserver import SessionLocal
from app.services.fusion_service import FusionService
from app.utils.network_resilience import summarize_network_error

router = APIRouter(prefix="/fusion-ai-v2", tags=["fusion AI V2"])
service = FusionService()


@router.get("/fusion/{symbol}")
def fusion(
    symbol: str,
    timeframe: str = Query(default="5m"),
    stale_after_seconds: int = Query(default=900, ge=1),
):

    db = SessionLocal()

    try:

        result = service.generate(db, symbol, timeframe, stale_after_seconds)

        return result

    except Exception as exc:
        db.rollback()
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "status": "FAILED",
            "error": summarize_network_error(exc),
            "freshness": {"is_stale": True},
        }

    finally:

        db.close()
