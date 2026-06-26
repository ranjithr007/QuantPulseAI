from app.database.sqlserver import SessionLocal

from app.database.models.market_features import MarketFeature
from app.database.models.market_regimes import MarketRegime
from app.repositories._db_utils import commit_or_rollback

from app.regimes.regime_engine import analyze_market
from app.utils.network_resilience import summarize_network_error


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

        commit_or_rollback(db)

        print("Regime Analysis Completed")
        return {
            "source": "v3_regime_engine",
            "processed": len(features),
            "saved": saved,
            "engine_version": "v3_regime_13_v1",
        }

    except Exception as e:

        print("Regime Error:", summarize_network_error(e))
        return {
            "source": "v3_regime_engine",
            "processed": 0,
            "saved": 0,
            "error": summarize_network_error(e),
        }

    finally:

        db.close()
