from fastapi import APIRouter, Query

from app.database.sqlserver import SessionLocal

from app.database.models.market_order_flow import MarketOrderFlow
from app.utils.freshness import with_freshness


router = APIRouter(prefix="/orderflow", tags=["Order Flow"])


@router.get("/{symbol}")
def get_orderflow(
    symbol: str,
    timeframe: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    stale_after_seconds: int = Query(default=900, ge=1),
):

    db = SessionLocal()

    try:

        query = db.query(MarketOrderFlow).filter(MarketOrderFlow.Symbol == symbol)

        if timeframe:

            query = query.filter(MarketOrderFlow.Timeframe == timeframe)

        records = (
            query.order_by(MarketOrderFlow.CreatedAt.desc())
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
