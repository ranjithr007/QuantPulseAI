from app.database.sqlserver import SessionLocal

from app.database.models.market_features import MarketFeature
from app.database.models.market_regimes import MarketRegime
from app.repositories._db_utils import commit_or_rollback
from app.repositories.symbol_repository import SymbolRepository
from sqlalchemy import func

from app.governance.evidence_policy import OFFICIAL_ENTRY_TIMEFRAMES
from app.regimes.regime_engine import analyze_market
from app.regimes.regime_engine import parse_regime_audit
from app.regimes.rules import REGIME_DEFINITIONS
from app.utils.network_resilience import summarize_network_error


def run_regime_analysis(*, context=None):

    db = SessionLocal()

    try:

        print("Starting Regime Analysis...")
        results=[]
        active_symbols = [
            item.symbol for item in SymbolRepository().get_active_symbols(db)
        ]
        if not active_symbols:
            return []
        latest_feature_ids = (
            db.query(MarketFeature)
            .with_entities(func.max(MarketFeature.Id).label("feature_id"))
            .filter(MarketFeature.Symbol.in_(active_symbols))
            .filter(MarketFeature.Timeframe.in_(OFFICIAL_ENTRY_TIMEFRAMES))
            .group_by(
                MarketFeature.Symbol,
                MarketFeature.Timeframe,
            )
            .subquery()
        )
        features = (
            db.query(MarketFeature)
            .filter(MarketFeature.Id.in_(db.query(latest_feature_ids.c.feature_id)))
            .order_by(MarketFeature.Symbol.asc(), MarketFeature.Timeframe.asc())
            .all()
        )

        saved = 0

        for feature in features:

            existing = (
                db.query(MarketRegime)
                .filter(
                    MarketRegime.Symbol == feature.Symbol,
                    MarketRegime.Timeframe == feature.Timeframe,
                    MarketRegime.CreatedAt == feature.CreatedAt,
                )
                .order_by(MarketRegime.Id.desc())
                .first()
            )
            if existing is not None:
                results.append(_existing_regime_result(existing))
                continue

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
                data_generation_id=(
                    context.generation_id if context is not None else None
                ),
                CreatedAt=feature.CreatedAt,
            )

            db.add(regime)
            results.append(result)
            saved += 1

        commit_or_rollback(db)

        print("Regime Analysis Completed")
        return results

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


def _existing_regime_result(record):
    audit = parse_regime_audit(record.Reason) or {}
    definition = REGIME_DEFINITIONS.get(record.Regime, {})
    return {
        "symbol": record.Symbol,
        "timeframe": record.Timeframe,
        "regime": record.Regime,
        "confidence": record.Confidence,
        "strategy": record.RecommendedStrategy,
        "bias": definition.get("bias"),
        "direction": definition.get("direction"),
        "risk_mode": definition.get("risk_mode"),
        "dwell_cycles": int(audit.get("dwell_cycles") or 1),
        "transition_decision": audit.get("transition_decision"),
        "transition_confidence": audit.get("transition_confidence"),
        "audit": audit,
        "reason": record.Reason,
        "persisted": False,
    }
