from fastapi import APIRouter, Depends

from sqlalchemy.orm import Session

from app.database.sqlserver import Base

from app.ml.dataset_builder import DatasetBuilder


router = APIRouter(prefix="/dataset", tags=["AI Dataset"])


@router.post("/{symbol}")
def build(symbol: str, db: Session = Depends(Base)):

    result = DatasetBuilder(db).build(symbol)

    return result