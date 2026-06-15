import joblib
import pandas as pd

from sklearn.preprocessing import LabelEncoder

from app.database.models.market_features import MarketFeature
from app.database.models.market_regimes import MarketRegime
from app.database.models.market_order_flow import MarketOrderFlow
from app.database.models.market_smc import MarketSMCSignal


class PredictionEngine:

    MODEL_PATH = "models/quantpulse_xgb.pkl"

    def __init__(self, db):
        self.db = db

    def predict(self, symbol: str):

        model = joblib.load(self.MODEL_PATH)

        feature = (
            self.db.query(MarketFeature)
            .filter(MarketFeature.Symbol == symbol)
            .order_by(MarketFeature.CreatedAt.desc())
            .first()
        )

        regime = (
            self.db.query(MarketRegime)
            .filter(MarketRegime.Symbol == symbol)
            .order_by(MarketRegime.CreatedAt.desc())
            .first()
        )

        flow = (
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

        if not feature:

            return {"error": "No market features"}

        data = {
            "trend_score": feature.TrendScore,
            "momentum_score": feature.MomentumScore,
            "volatility_score": feature.VolatilityScore,
            "regime": regime.Regime if regime else "UNKNOWN",
            "regime_confidence": regime.Confidence if regime else 0,
            "cvd": flow.CVD if flow else 0,
            "delta": flow.Delta if flow else 0,
            "smc_bias": smc.smc_bias if smc else "NONE",
            "smc_confidence": smc.confidence if smc else 0,
        }

        df = pd.DataFrame([data])

        for col in ["regime", "smc_bias"]:
            enc = LabelEncoder()

            df[col] = enc.fit_transform(df[col])

        prediction = model.predict(df)[0]

        probability = model.predict_proba(df).max()

        signal_map = {0: "SHORT", 1: "HOLD", 2: "LONG"}

        return {
            "symbol": symbol,
            "signal": signal_map[prediction],
            "confidence": round(probability * 100, 2),
            "features": data,
        }