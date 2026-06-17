from fastapi import APIRouter, Query

from app.database.sqlserver import SessionLocal

from app.database.models.market_features import MarketFeature
from app.utils.freshness import with_freshness


router = APIRouter(prefix="/features", tags=["Market Features"])


@router.get("/{symbol}")
def get_features(
    symbol: str,
    timeframe: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    stale_after_seconds: int = Query(default=900, ge=1),
):

    db = SessionLocal()

    try:

        query = db.query(MarketFeature).filter(MarketFeature.Symbol == symbol)

        if timeframe:

            query = query.filter(MarketFeature.Timeframe == timeframe)

        records = (
            query.order_by(MarketFeature.CreatedAt.desc())
            .limit(limit)
            .all()
        )

        items = [
            with_freshness(record, "CreatedAt", stale_after_seconds)
            for record in records
        ]

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "count": len(items),
            "latest": items[0] if items else None,
            "records": items,
        }

    finally:

        db.close()
