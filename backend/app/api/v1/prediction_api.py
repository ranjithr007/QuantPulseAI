from fastapi import APIRouter, HTTPException

from app.database.sqlserver import SessionLocal


router = APIRouter(prefix="/ai", tags=["AI Prediction"])


@router.get("/predict/{symbol}")
def predict(symbol: str):
    db = SessionLocal()

    try:

        try:
            from app.ml.predictor import PredictionEngine
        except ModuleNotFoundError as exc:
            raise HTTPException(
                status_code=503,
                detail=f"ML dependency is not installed: {exc.name}",
            ) from exc

        return PredictionEngine(db).predict(symbol)

    except Exception:
        db.rollback()
        raise

    finally:

        db.close()
