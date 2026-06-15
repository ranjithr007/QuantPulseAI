from app.database.models.market_features import MarketFeature


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
        ATR=feature.get("atr", 0)
    )

    db.add(record)

    db.commit()

    db.refresh(record)

    return record


def get_latest_feature(db, symbol):

    return (
        db.query(MarketFeature)
        .filter(MarketFeature.Symbol == symbol)
        .order_by(MarketFeature.CreatedAt.desc())
        .first()
    )