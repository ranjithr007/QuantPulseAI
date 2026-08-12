from fastapi import APIRouter, Query

from app.api.v2.master_ai_v2_api import build_master_ai_response


router = APIRouter(prefix="/master-ai", tags=["Master AI"])


@router.get("/{symbol}")
def master_ai(
    symbol: str,
    timeframe: str = Query(default="5m", enum=["1m", "5m", "15m", "1h", "2h", "4h", "1d"]),
    stale_after_seconds: int = Query(default=900, ge=1),
):
    return build_master_ai_response(symbol, timeframe, stale_after_seconds)
