from app.intelligence.fusion.fusion_engine import FusionEngine
from app.intelligence.fusion.fusion_models import FusionInput

from app.repositories.intelligence_repository import IntelligenceRepository
from app.repositories.fusion_repository import FusionSignalRepository
from app.utils.freshness import freshness_status


class FusionService:

    def __init__(self):

        self.engine = FusionEngine()

        self.repo = IntelligenceRepository()
        self.fusion_repository = FusionSignalRepository()

    def generate(
        self,
        db,
        symbol,
        timeframe: str = "5m",
        stale_after_seconds: int = 900,
        *,
        context=None,
    ):

        feature = self.repo.get_latest_feature(db, symbol, timeframe)
        regime = self.repo.get_latest_regime(db, symbol, timeframe)
        orderflow = self.repo.get_latest_orderflow(db, symbol, timeframe)
        smc = self.repo.get_latest_smc(db, symbol, timeframe)

        # print("REGIME confidence:", regime.Confidence)

        # print("ORDERFLOW confidence:", orderflow.Confidence)

        # print("SMC confidence:", smc.confidence)

        # print("FEATURE liquidity:", feature.LiquidityScore)

        data = FusionInput(
            symbol=symbol,
            timeframe=timeframe, 
            # ML later
            ml_score=0,
            # Regime engine
            regime_score=(regime.Confidence if regime else 0),
            # Orderflow engine
            orderflow_score=(orderflow.Confidence if orderflow else 0),
            # SMC engine
            smc_score=(smc.confidence if smc else 0),
            # From Feature Factory
            liquidation_score=(feature.LiquidityScore if feature else 0),
            # later whale engine
            whale_score=0,
        )

        result = self.engine.analyze(data)
        result["timeframe"] = timeframe
        if context is not None:
            result["data_generation_id"] = context.generation_id

        # SAVE FUSION RESULT 
        saved_signal = self.fusion_repository.save(db, result)

        # print("Fusion Result:", result)
        return {
            "id": saved_signal.id,
            "symbol": saved_signal.symbol,
            "timeframe": saved_signal.timeframe,
            "decision": saved_signal.decision,
            "confidence": saved_signal.confidence,
            "scores": {
                "ml_score": saved_signal.ml_score,
                "regime_score": saved_signal.regime_score,
                "orderflow_score": saved_signal.orderflow_score,
                "smc_score": saved_signal.smc_score,
                "liquidation_score": saved_signal.liquidation_score,
                "whale_score": saved_signal.whale_score,
            },
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
            "created_at": saved_signal.created_at,
            "freshness": freshness_status(saved_signal.created_at, stale_after_seconds),
        }
