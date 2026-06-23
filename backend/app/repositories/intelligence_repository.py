from app.database.models.market_features import MarketFeature
from app.database.models.market_regimes import MarketRegime
from app.database.models.market_order_flow import MarketOrderFlow
from app.database.models.market_smc import MarketSMCSignal


class IntelligenceRepository:

    def get_latest_feature(self, db, symbol, timeframe: str):

        return (
            db.query(MarketFeature)
            .filter(MarketFeature.Symbol == symbol, MarketFeature.Timeframe==timeframe)
            .order_by(MarketFeature.Id.desc())
            .first()
        )

    def get_latest_regime(self, db, symbol, timeframe: str):

        return (
            db.query(MarketRegime)
            .filter(MarketRegime.Symbol == symbol, MarketRegime.Timeframe==timeframe)
            .order_by(MarketRegime.Id.desc())
            .first()
        )

    def get_latest_orderflow(self, db, symbol, timeframe: str):

        return (
            db.query(MarketOrderFlow)
            .filter(MarketOrderFlow.Symbol == symbol, MarketOrderFlow.Timeframe==timeframe)
            .order_by(MarketOrderFlow.Id.desc())
            .first()
        )

    def get_latest_smc(self, db, symbol, timeframe: str):

        return (
            db.query(MarketSMCSignal)
            .filter(MarketSMCSignal.symbol == symbol, MarketSMCSignal.timeframe==timeframe)
            .order_by(MarketSMCSignal.id.desc())
            .first()
        )

    def get_latest_ml(self, db, symbol):

        return None


# ==================================================
# Backward compatibility for master_ai_v2_api.py
# IMPORTANT: this must NOT be inside the class
# ==================================================


def get_ai_inputs(db, symbol, timeframe: str = "5m"):
    cache = _session_cache(db, "quantpulse_ai_inputs")
    cache_key = (symbol, timeframe)
    if cache is not None and cache_key in cache:
        return cache[cache_key]

    repo = IntelligenceRepository()

    feature = repo.get_latest_feature(db, symbol, timeframe)

    regime = repo.get_latest_regime(db, symbol, timeframe)

    orderflow = repo.get_latest_orderflow(db, symbol, timeframe)

    smc = repo.get_latest_smc(db, symbol, timeframe)

    inputs = {"feature": feature, "regime": regime, "orderflow": orderflow, "smc": smc}
    if cache is not None:
        cache[cache_key] = inputs

    return inputs


def _session_cache(db, key):
    info = getattr(db, "info", None)
    if not isinstance(info, dict):
        return None

    return info.setdefault(key, {})
