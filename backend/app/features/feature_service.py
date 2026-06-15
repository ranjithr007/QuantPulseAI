from app.database.sqlserver import SessionLocal

from app.features.feature_factory import build_features

from app.repositories.feature_repository import save_market_feature
from app.repositories.candle_repository import get_latest_candles


def generate_features(symbol, timeframe):

    db = SessionLocal()

    try:

        candles = get_latest_candles(db, symbol, timeframe)

        features = build_features(symbol, timeframe, candles)

        save_market_feature(db, features)

        return features

    finally:

        db.close()