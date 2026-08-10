from app.database.models.market_features import MarketFeature
from app.repositories._db_utils import commit_or_rollback


def save_market_feature(db, feature):

    record = MarketFeature(
        Symbol=feature["symbol"],
        Timeframe=feature["timeframe"],
        TrendScore=feature["trend_score"],
        MomentumScore=feature["momentum_score"],
        VolatilityScore=feature.get("volatility_score", 0),
        LiquidityScore=feature.get("liquidity_score", 0),
        FinalScore=feature["final_score"],
        Trend=feature["trend"],
        Signal=feature["signal"],
        ATR=feature.get("atr", 0),
        data_generation_id=feature.get("data_generation_id"),
    )

    db.add(record)

    commit_or_rollback(db)

    db.refresh(record)

    return record


def get_latest_feature(db, symbol, timeframe=None):

    query = db.query(MarketFeature).filter(MarketFeature.Symbol == symbol)

    if timeframe:
        query = query.filter(MarketFeature.Timeframe == timeframe)

    return query.order_by(MarketFeature.CreatedAt.desc()).first()
