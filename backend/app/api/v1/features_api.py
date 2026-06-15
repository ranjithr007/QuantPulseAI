from fastapi import APIRouter

from app.database.sqlserver import SessionLocal

from app.database.models.market_features import MarketFeature


router = APIRouter(prefix="/features", tags=["Market Features"])


@router.get("/{symbol}")
def get_features(symbol: str):

    db = SessionLocal()

    data = (
        db.query(MarketFeature)
        .filter(MarketFeature.Symbol == symbol)
        .order_by(MarketFeature.CreatedAt.desc())
        .limit(20)
        .all()
    )

    db.close()

    return data