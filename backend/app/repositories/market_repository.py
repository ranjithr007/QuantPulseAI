from datetime import datetime

from app.database.models.market_candles import MarketCandle


class MarketRepository:

    def save_candle(self, db, candle):

        candle_time = datetime.fromtimestamp(candle["open_time_ms"] / 1000)

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
        result = (
            db.query(MarketCandle.candle_time)
            .filter_by(symbol=symbol, timeframe=timeframe)
            .order_by(MarketCandle.candle_time.desc())
            .first()
        )
        return result[0] if result else None