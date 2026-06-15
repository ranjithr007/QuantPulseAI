from fastapi import APIRouter

from app.database.sqlserver import SessionLocal

from app.database.models.market_order_flow import MarketOrderFlow


router = APIRouter(prefix="/orderflow", tags=["Order Flow"])


@router.get("/{symbol}")
def get_orderflow(symbol: str):

    db = SessionLocal()

    result = (
        db.query(MarketOrderFlow)
        .filter(MarketOrderFlow.Symbol == symbol)
        .order_by(MarketOrderFlow.CreatedAt.desc())
        .limit(20)
        .all()
    )

    db.close()

    return result