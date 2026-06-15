from app.database.sqlserver import SessionLocal

from app.repositories.market_price_repository import MarketPriceRepository


class MarketPriceService:

    def __init__(self):

        self.repo = MarketPriceRepository()

    def get_latest_price(self, symbol):

        db = SessionLocal()

        try:

            candle = self.repo.get_latest_candle(db, symbol)

            if candle is None:

                return None

            return float(candle.close)

        finally:

            db.close()