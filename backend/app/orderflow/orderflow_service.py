from sqlalchemy import true
from app.database.sqlserver import SessionLocal

from app.repositories.candle_repository import get_latest_candles, get_latest_candle

from app.repositories.orderflow_repository import OrderFlowRepository

from app.orderflow.delta_engine import analyze_orderflow


def generate_orderflow(symbol, timeframe, *, context=None):

    db = SessionLocal()

    try:

        candles = get_latest_candles(db, symbol, timeframe)

        if len(candles) < 20:

            return None
        latest_record = OrderFlowRepository.get_last_cvd(db, symbol)
        
        result = analyze_orderflow(candles,latest_record,True)
        if context is not None:
            result["data_generation_id"] = context.generation_id

        OrderFlowRepository.save_orderflow(db, symbol, timeframe, result)

        return result

    except Exception:
        db.rollback()
        raise

    finally:

        db.close()
