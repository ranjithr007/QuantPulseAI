from datetime import datetime
from datetime import timedelta
from datetime import timezone

from app.database.models.market_candles import MarketCandle
from app.utils.freshness import normalize_timestamp_to_utc


FUTURE_CANDLE_TOLERANCE_SECONDS = 60


def _normalized_candle_time(candle):
    return normalize_timestamp_to_utc(candle.candle_time)


def get_latest_candles(db, symbol, timeframe, limit=200):

    candidate_limit = max(limit * 4, 500)
    raw_time_candidates = (
        db.query(MarketCandle)
        .filter(MarketCandle.symbol == symbol)
        .filter(MarketCandle.timeframe == timeframe)
        .order_by(MarketCandle.candle_time.desc())
        .limit(candidate_limit)
        .all()
    )
    recent_insert_candidates = (
        db.query(MarketCandle)
        .filter(MarketCandle.symbol == symbol)
        .filter(MarketCandle.timeframe == timeframe)
        .order_by(MarketCandle.id.desc())
        .limit(candidate_limit)
        .all()
    )
    candidates = {
        candle.id: candle
        for candle in raw_time_candidates + recent_insert_candidates
    }.values()
    now = datetime.now(timezone.utc)
    max_usable_time = now + timedelta(seconds=FUTURE_CANDLE_TOLERANCE_SECONDS)
    usable_candidates = [
        candle
        for candle in candidates
        if _normalized_candle_time(candle) <= max_usable_time
    ]

    return sorted(
        usable_candidates,
        key=_normalized_candle_time,
        reverse=True,
    )[:limit]


def get_latest_candle(db, symbol, timeframe):
    candles = get_latest_candles(db, symbol, timeframe, limit=1)

    return candles[0] if candles else None
