from fastapi import APIRouter, Query

from app.database.models.ai_scores import AIScore
from app.database.sqlserver import SessionLocal
from app.repositories.intelligence_repository import get_ai_inputs
from app.utils.freshness import freshness_status
from app.utils.freshness import with_freshness


router = APIRouter(prefix="/ai-scores", tags=["AI Scores"])


@router.get("/{symbol}")
def get_ai_scores(
    symbol: str,
    timeframe: str = Query(default="5m"),
    limit: int = Query(default=20, ge=1, le=100),
    stale_after_seconds: int = Query(default=900, ge=1),
):
    db = SessionLocal()

    try:
        records = (
            db.query(AIScore)
            .filter(AIScore.symbol == symbol)
            .order_by(AIScore.created_at.desc())
            .limit(limit)
            .all()
        )

        items = [
            with_freshness(record, "created_at", stale_after_seconds)
            for record in records
        ]

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "source": "ai_scores" if items else "computed_current",
            "count": len(items),
            "latest": items[0] if items else None,
            "records": items,
            "computed": None
            if items
            else _compute_current_score(db, symbol, timeframe, stale_after_seconds),
        }

    finally:
        db.close()


def _compute_current_score(db, symbol, timeframe, stale_after_seconds):
    inputs = get_ai_inputs(db, symbol, timeframe)
    feature = inputs["feature"]
    orderflow = inputs["orderflow"]
    smc = inputs["smc"]
    regime = inputs["regime"]

    if not any([feature, orderflow, smc, regime]):
        return {
            "status": "NO_INPUTS",
            "message": "No feature/regime/orderflow/SMC inputs found for symbol/timeframe",
        }

    trend_score = _bounded(getattr(feature, "TrendScore", None), 50)
    liquidity_score = _bounded(getattr(feature, "LiquidityScore", None), 50)
    volatility_score = _bounded(getattr(feature, "VolatilityScore", None), 50)
    derivative_score = _bounded(getattr(orderflow, "Confidence", None), 50)
    whale_score = _bounded(getattr(smc, "confidence", None), 50)
    sentiment_score = 50

    final_score = round(
        trend_score * 0.25
        + liquidity_score * 0.20
        + derivative_score * 0.20
        + volatility_score * 0.15
        + whale_score * 0.10
        + sentiment_score * 0.10,
        2,
    )

    if final_score >= 65:
        bias = "BULLISH"
    elif final_score <= 35:
        bias = "BEARISH"
    else:
        bias = "NEUTRAL"

    return {
        "status": "COMPUTED_NOT_PERSISTED",
        "symbol": symbol,
        "timeframe": timeframe,
        "trend_score": trend_score,
        "liquidity_score": liquidity_score,
        "derivative_score": derivative_score,
        "volatility_score": volatility_score,
        "whale_score": whale_score,
        "sentiment_score": sentiment_score,
        "final_score": final_score,
        "bias": bias,
        "confidence": abs(final_score - 50) * 2,
        "inputs": {
            "feature": freshness_status(
                getattr(feature, "CreatedAt", None),
                stale_after_seconds,
            ),
            "regime": freshness_status(
                getattr(regime, "CreatedAt", None),
                stale_after_seconds,
            ),
            "orderflow": freshness_status(
                getattr(orderflow, "CreatedAt", None),
                stale_after_seconds,
            ),
            "smc": freshness_status(
                getattr(smc, "created_at", None),
                stale_after_seconds,
            ),
        },
    }


def _bounded(value, default):
    if value is None:
        return default

    return max(0, min(100, float(value)))
