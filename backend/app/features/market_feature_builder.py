from app.database.models.funding_rates import FundingRate
from app.database.models.open_interest import OpenInterest
from app.repositories.candle_repository import get_latest_candles


class MarketFeatureBuilder:

    def build(self, db, symbol):

        candles = get_latest_candles(db, symbol, "1h", limit=2)

        if len(candles) < 2:
            return None
        latest = candles[-1]
        previous = candles[-2]
        price_change = (
            (latest.close_price - previous.close_price) / previous.close_price
        ) * 100

        funding = (
            db.query(FundingRate)
            .filter(FundingRate.symbol == symbol)
            .order_by(FundingRate.funding_time.desc(), FundingRate.id.desc())
            .first()
        )

        oi = (
            db.query(OpenInterest)
            .filter(OpenInterest.symbol == symbol)
            .order_by(OpenInterest.timestamp.desc(), OpenInterest.id.desc())
            .limit(2)
            .all()
        )

        oi_change = 0

        if len(oi) == 2:
            if oi[1].value != 0:
                oi_change = ((oi[0].value - oi[1].value) / oi[1].value) * 100

        return {
            "symbol": symbol,
            "price_change": price_change,
            "funding": funding.rate if funding else 0,
            "oi_change": oi_change,
        }
