from fastapi import APIRouter, Query

from app.database.sqlserver import SessionLocal

from app.database.models.market_smc import MarketSMCSignal
from app.utils.network_resilience import summarize_network_error
from app.utils.freshness import with_freshness


router = APIRouter(prefix="/smc", tags=["SMC"])


def _smc_error_payload(symbol, timeframe, exc):
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "source": "smc_signals",
        "count": 0,
        "latest": None,
        "records": [],
        "status": "FAILED",
        "error": summarize_network_error(exc),
    }


@router.get("/{symbol}")
def get_smc(
    symbol: str,
    timeframe: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    stale_after_seconds: int = Query(default=900, ge=1),
):

    db = SessionLocal()

    try:
        return build_smc_payload(
            db,
            symbol,
            timeframe,
            limit,
            stale_after_seconds,
        )

    except Exception as exc:
        db.rollback()
        return _smc_error_payload(symbol, timeframe, exc)

    finally:
        db.close()


def build_smc_payload(db, symbol, timeframe=None, limit=20, stale_after_seconds=900):
    query = db.query(MarketSMCSignal).filter(MarketSMCSignal.symbol == symbol)

    if timeframe:
        query = query.filter(MarketSMCSignal.timeframe == timeframe)

    records = (
        query.order_by(MarketSMCSignal.created_at.desc())
        .limit(limit)
        .all()
    )
    items = [
        with_freshness(record, "created_at", stale_after_seconds)
        for record in records
    ]

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "count": len(items),
        "latest": items[0] if items else None,
        "records": items,
    }
