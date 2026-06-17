from app.database.sqlserver import SessionLocal

from app.database.models.market_features import MarketFeature
from app.database.models.market_regimes import MarketRegime

from app.regimes.regime_engine import analyze_market


def run_regime_analysis():

    db = SessionLocal()

    try:

        print("Starting Regime Analysis...")

        features = (
            db.query(MarketFeature)
            .order_by(MarketFeature.CreatedAt.desc())
            .limit(50)
            .all()
        )

        saved = 0

        for feature in features:

            previous = (
                db.query(MarketRegime)
                .filter(
                    MarketRegime.Symbol == feature.Symbol,
                    MarketRegime.Timeframe == feature.Timeframe,
                )
                .order_by(MarketRegime.Id.desc())
                .first()
            )

            result = analyze_market(feature, previous)

            regime = MarketRegime(
                Symbol=result["symbol"],
                Timeframe=result["timeframe"],
                Regime=result["regime"],
                Confidence=result["confidence"],
                RecommendedStrategy=result["strategy"],
                Reason=result["reason"],
            )

            db.add(regime)
            saved += 1

        db.commit()

        print("Regime Analysis Completed")
        return {
            "source": "v3_regime_engine",
            "processed": len(features),
            "saved": saved,
            "engine_version": "v3_regime_13_v1",
        }

    except Exception as e:

        print("Regime Error:", e)
        return {
            "source": "v3_regime_engine",
            "processed": 0,
            "saved": 0,
            "error": str(e),
        }

    finally:

        db.close()
