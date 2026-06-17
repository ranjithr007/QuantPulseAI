from app.repositories.candle_repository import get_latest_candle


class MarketPriceRepository:

    def get_latest_candle(self, db, symbol, timeframe="5m"):

        return get_latest_candle(db, symbol, timeframe)
