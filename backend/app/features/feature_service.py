from app.database.sqlserver import SessionLocal

from app.features.point_in_time_feature_service import build_feature_snapshot
from app.features.point_in_time_feature_service import persist_feature_snapshot
from app.repositories.candle_repository import get_latest_candles
from app.repositories.feature_repository import save_market_feature


def generate_features(symbol, timeframe):

    db = SessionLocal()

    try:

        candles = get_latest_candles(db, symbol, timeframe)

        snapshot = build_feature_snapshot(symbol, timeframe, candles)
        features = snapshot["feature"]

        save_market_feature(db, features)
        persist_feature_snapshot(db, snapshot)

        return features

    except Exception:
        db.rollback()
        raise

    finally:

        db.close()
