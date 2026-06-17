from datetime import datetime
from datetime import timedelta
from datetime import timezone

from app.database.models.market_candles import MarketCandle
from app.repositories.candle_repository import get_latest_candle


FUTURE_CANDLE_TOLERANCE_SECONDS = 60


class MarketRepository:

    def save_candle(self, db, candle):

        candle_time = datetime.fromtimestamp(
            candle["open_time_ms"] / 1000,
            timezone.utc,
        ).replace(tzinfo=None)
        candle_time_utc = candle_time.replace(tzinfo=timezone.utc)
        max_usable_time = datetime.now(timezone.utc) + timedelta(
            seconds=FUTURE_CANDLE_TOLERANCE_SECONDS
        )

        if candle_time_utc > max_usable_time:
            return

        exists = (
            db.query(MarketCandle)
            .filter(
                MarketCandle.symbol == candle["symbol"],
                MarketCandle.timeframe == candle["timeframe"],
                MarketCandle.candle_time == candle_time,
            )
            .first()
        )

        if exists:

            return

        entity = MarketCandle(
            symbol=candle["symbol"],
            timeframe=candle["timeframe"],
            open_price=candle["open"],
            high_price=candle["high"],
            low_price=candle["low"],
            close_price=candle["close"],
            volume=candle["volume"],
            candle_time=candle_time,
        )

        db.add(entity)

        db.commit()

    def get_last_candle_time(self, db, symbol: str, timeframe: str):
        candle = get_latest_candle(db, symbol, timeframe)

        return candle.candle_time if candle else None
