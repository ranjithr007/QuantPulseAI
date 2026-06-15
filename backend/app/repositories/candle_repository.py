from app.database.models.market_candles import MarketCandle


def get_latest_candles(db, symbol, timeframe, limit=200):

    return (
        db.query(MarketCandle)
        .filter(MarketCandle.symbol == symbol)
        .filter(MarketCandle.timeframe == timeframe)
        .order_by(MarketCandle.candle_time.desc())
        .limit(limit)
        .all()
    )