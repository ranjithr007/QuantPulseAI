from app.database.models.market_candles import MarketCandle
from app.database.models.funding_rates import FundingRate
from app.database.models.open_interest import OpenInterest


class MarketFeatureBuilder:

    def build(self, db, symbol):

        candles = (
            db.query(MarketCandle)
            .filter(MarketCandle.symbol == symbol)
            .order_by(MarketCandle.candle_time.desc())
            .limit(2)
            .all()
        )

        if len(candles) < 2:

            return None

        latest = candles[0]

        previous = candles[1]

        price_change = (
            (latest.close_price - previous.close_price) / previous.close_price
        ) * 100

        funding = (
            db.query(FundingRate)
            .filter(FundingRate.symbol == symbol)
            .order_by(FundingRate.created_at.desc())
            .first()
        )

        oi = (
            db.query(OpenInterest)
            .filter(OpenInterest.symbol == symbol)
            .order_by(OpenInterest.created_at.desc())
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