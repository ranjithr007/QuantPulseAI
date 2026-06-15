from app.intelligence.fusion.fusion_engine import FusionEngine
from app.intelligence.fusion.fusion_models import FusionInput

from app.repositories.intelligence_repository import IntelligenceRepository
from app.repositories.fusion_repository import FusionSignalRepository


class FusionService:

    def __init__(self):

        self.engine = FusionEngine()

        self.repo = IntelligenceRepository()
        self.fusion_repository = FusionSignalRepository()

    def generate(self, db, symbol, timeframe: str = "5m"):

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

        # SAVE FUSION RESULT 
        saved_signal = self.fusion_repository.save(db, result)

        # print("Fusion Result:", result)
        return saved_signal