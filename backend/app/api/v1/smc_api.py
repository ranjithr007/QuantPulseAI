from fastapi import APIRouter

from app.database.sqlserver import SessionLocal

from app.database.models.market_smc import MarketSMCSignal


router = APIRouter(prefix="/smc", tags=["SMC"])


@router.get("/{symbol}")
def get_smc(symbol: str):

    db = SessionLocal()

    result = (
        db.query(MarketSMCSignal)
        .filter(MarketSMCSignal.symbol == symbol)
        .order_by(MarketSMCSignal.created_at.desc())
        .limit(20)
        .all()
    )

    db.close()

    return result