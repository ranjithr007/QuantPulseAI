from fastapi import APIRouter
from fastapi import HTTPException

from app.database.sqlserver import SessionLocal
from app.repositories.market_participation_repository import MarketParticipationRepository
from app.repositories.symbol_repository import SymbolRepository


router = APIRouter(prefix="/market-participation", tags=["Market Participation"])


@router.get("/trend/{symbol}")
def get_market_participation_trend(symbol: str):
    db = SessionLocal()
    try:
        payload = MarketParticipationRepository().latest(db, symbol)
        if payload is None:
            raise HTTPException(
                status_code=404,
                detail="Market participation trend has not been calculated yet",
            )
        return payload
    finally:
        db.close()


@router.get("/trends")
def get_market_participation_trends():
    db = SessionLocal()
    try:
        symbols = [
            item.symbol
            for item in SymbolRepository().get_active_symbols(db)
        ]
        rows = MarketParticipationRepository().latest_for_symbols(db, symbols)
        records = [rows[symbol] for symbol in symbols if rows.get(symbol) is not None]
        return {
            "source": "market_participation_trends",
            "count": len(records),
            "records": records,
        }
    finally:
        db.close()
