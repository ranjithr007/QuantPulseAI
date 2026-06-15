from app.database.models.market_candles import MarketCandle


class MarketPriceRepository:

    def get_latest_candle(self, db, symbol):

        return (
            db.query(MarketCandle)
            .filter(MarketCandle.symbol == symbol)
            .order_by(MarketCandle.timestamp.desc())
            .first()
        )