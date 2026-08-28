from app.database.models.market_features import MarketFeature
from app.repositories._db_utils import commit_or_rollback
from app.utils.freshness import normalize_timestamp_to_naive_utc


def save_market_feature(db, feature, *, source_timestamp=None):
    evidence_timestamp = normalize_timestamp_to_naive_utc(source_timestamp)
    if evidence_timestamp is not None:
        existing = (
            db.query(MarketFeature)
            .filter(
                MarketFeature.Symbol == feature["symbol"],
                MarketFeature.Timeframe == feature["timeframe"],
                MarketFeature.CreatedAt == evidence_timestamp,
            )
            .order_by(MarketFeature.Id.desc())
            .first()
        )
        if existing is not None:
            return existing

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
    if evidence_timestamp is not None:
        record.CreatedAt = evidence_timestamp

    db.add(record)

    commit_or_rollback(db)

    db.refresh(record)

    return record


def get_latest_feature(db, symbol, timeframe=None):

    query = db.query(MarketFeature).filter(MarketFeature.Symbol == symbol)

    if timeframe:
        query = query.filter(MarketFeature.Timeframe == timeframe)

    return query.order_by(MarketFeature.CreatedAt.desc()).first()
