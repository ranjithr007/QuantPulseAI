from fastapi import APIRouter, Depends

from sqlalchemy.orm import Session

from app.database.sqlserver import SessionLocal

from app.ml.dataset_builder import DatasetBuilder

from app.ml.trainer import ModelTrainer


router = APIRouter(prefix="/ml", tags=["AI Model"])


@router.post("/train/{symbol}")
def train_model(symbol: str):
    db = SessionLocal()
    dataset = DatasetBuilder().build_dataset(db, symbol)

    if dataset is None:

        return {"error": "Not enough data"}

    result = ModelTrainer().train(dataset)

    return {"symbol": symbol, "result": result}