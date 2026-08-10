from app.database.sqlserver import SessionLocal

from app.features.point_in_time_feature_service import build_feature_snapshot
from app.features.point_in_time_feature_service import persist_feature_snapshot
from app.repositories.candle_repository import get_latest_candles
from app.repositories.feature_repository import save_market_feature


def generate_features(symbol, timeframe, *, context=None):

    db = SessionLocal()
    try:
        candles = get_latest_candles(db, symbol, timeframe)
        latest = candles[-1] if candles else None
        source_timestamp = (
            (
                getattr(latest, "open_time", None)
                or getattr(latest, "candle_time", None)
            )
            if latest is not None
            else None
        )
        effective_timestamp = (
            getattr(latest, "close_time", None)
            if latest is not None
            else None
        )
        snapshot = build_feature_snapshot(
            symbol,
            timeframe,
            candles,
            source_timestamp=source_timestamp,
            effective_timestamp=effective_timestamp,
        )
        features = snapshot["feature"]
        if context is not None:
            features["data_generation_id"] = context.generation_id
            snapshot["data_generation_id"] = context.generation_id
        save_market_feature(db, features)
        persist_feature_snapshot(db, snapshot)

        return features

    except Exception:
        db.rollback()
        raise

    finally:

        db.close()
