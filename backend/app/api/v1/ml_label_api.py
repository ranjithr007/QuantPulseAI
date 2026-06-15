from fastapi import APIRouter, Depends

from sqlalchemy.orm import Session

from app.database.sqlserver import SessionLocal

from app.ml.label_generator import LabelGenerator


router = APIRouter(prefix="/labels", tags=["ML Labels"])


@router.post("/{symbol}")
def create_labels(symbol: str):
    db = SessionLocal()
    return LabelGenerator(db).generate(symbol)