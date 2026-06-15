from sqlalchemy.orm import Session


from app.database.models.ml_training_data import MLTrainingData

from app.database.models.market_features import MarketFeature
from app.database.models.market_regimes import MarketRegime
from app.database.models.market_order_flow import MarketOrderFlow
from app.database.models.market_smc import MarketSMCSignal


class DatasetBuilder:

    def __init__(self, db: Session):
        self.db = db

    def build(self, symbol: str, timeframe: str = "1m"):

        features = (
            self.db.query(MarketFeature)
            .filter(MarketFeature.Symbol == symbol)
            .order_by(MarketFeature.CreatedAt.asc())
            .all()
        )

        count = 0

        for feature in features:

            regime = (
                self.db.query(MarketRegime)
                .filter(MarketRegime.Symbol == symbol)
                .order_by(MarketRegime.CreatedAt.desc())
                .first()
            )

            order_flow = (
                self.db.query(MarketOrderFlow)
                .filter(MarketOrderFlow.Symbol == symbol)
                .order_by(MarketOrderFlow.CreatedAt.desc())
                .first()
            )

            smc = (
                self.db.query(MarketSMCSignal)
                .filter(MarketSMCSignal.symbol == symbol)
                .order_by(MarketSMCSignal.created_at.desc())
                .first()
            )

            row = MLTrainingData(
                symbol=symbol,
                timeframe=timeframe,
                # FEATURES
                trend_score=feature.TrendScore,
                momentum_score=feature.MomentumScore,
                volatility_score=feature.VolatilityScore,
                # REGIME
                regime=regime.Regime if regime else None,
                regime_confidence=regime.Confidence if regime else None,
                # ORDERFLOW
                cvd=order_flow.CVD if order_flow else None,
                delta=order_flow.Delta if order_flow else None,
                # SMC
                smc_bias=smc.smc_bias if smc else None,
                smc_confidence=smc.confidence if smc else None,
                label=None,
            )

            self.db.add(row)

            count += 1

        self.db.commit()

        return {"created": count}