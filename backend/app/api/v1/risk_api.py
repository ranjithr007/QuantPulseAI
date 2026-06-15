from fastapi import APIRouter

from app.repositories.risk_repository import RiskRepository

router = APIRouter(prefix="/risk")


repo = RiskRepository()


@router.get("/{symbol}")
def get_risk(symbol: str):

    return repo.latest(symbol)