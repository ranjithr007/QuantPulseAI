from fastapi import APIRouter, HTTPException

from app.database.sqlserver import SessionLocal


router = APIRouter(prefix="/ml", tags=["AI Model"])


@router.post("/train/{symbol}")
def train_model(symbol: str):
    db = SessionLocal()

    try:

        try:
            from app.ml.dataset_builder import DatasetBuilder
            from app.ml.trainer import ModelTrainer
        except ModuleNotFoundError as exc:
            raise HTTPException(
                status_code=503,
                detail=f"ML dependency is not installed: {exc.name}",
            ) from exc

        dataset = DatasetBuilder(db).build(symbol)

        if dataset is None:

            return {"error": "Not enough data"}

        result = ModelTrainer(db).train()

        return {"symbol": symbol, "dataset": dataset, "result": result}

    finally:

        db.close()
