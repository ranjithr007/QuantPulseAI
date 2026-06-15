from fastapi import APIRouter, Depends

from sqlalchemy.orm import Session

from app.database.sqlserver import SessionLocal

from app.ml.predictor import PredictionEngine


router = APIRouter(prefix="/ai", tags=["AI Prediction"])


@router.get("/predict/{symbol}")
def predict(symbol: str):
    db = SessionLocal()
    return PredictionEngine(db).predict(symbol)