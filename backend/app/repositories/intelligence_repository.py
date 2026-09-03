from app.database.models.market_features import MarketFeature
from app.database.models.market_regimes import MarketRegime
from app.database.models.market_order_flow import MarketOrderFlow
from app.database.models.market_smc import MarketSMCSignal
from sqlalchemy import func


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


def prime_ai_inputs_cache(db, symbols, timeframe: str = "5m"):
    """Prime current feature inputs for a multi-symbol scanner in four queries."""
    cache = _session_cache(db, "quantpulse_ai_inputs")
    normalized = sorted({str(symbol).strip().upper() for symbol in symbols or [] if symbol})
    if cache is None or not normalized:
        return

    missing = [symbol for symbol in normalized if (symbol, timeframe) not in cache]
    if not missing:
        return

    features = _latest_rows_by_symbol(
        db, MarketFeature, MarketFeature.Symbol, MarketFeature.Timeframe, MarketFeature.Id, missing, timeframe
    )
    regimes = _latest_rows_by_symbol(
        db, MarketRegime, MarketRegime.Symbol, MarketRegime.Timeframe, MarketRegime.Id, missing, timeframe
    )
    orderflows = _latest_rows_by_symbol(
        db, MarketOrderFlow, MarketOrderFlow.Symbol, MarketOrderFlow.Timeframe, MarketOrderFlow.Id, missing, timeframe
    )
    smc_rows = _latest_rows_by_symbol(
        db, MarketSMCSignal, MarketSMCSignal.symbol, MarketSMCSignal.timeframe, MarketSMCSignal.id, missing, timeframe
    )
    for symbol in missing:
        cache[(symbol, timeframe)] = {
            "feature": features.get(symbol),
            "regime": regimes.get(symbol),
            "orderflow": orderflows.get(symbol),
            "smc": smc_rows.get(symbol),
        }


def _latest_rows_by_symbol(
    db,
    model,
    symbol_column,
    timeframe_column,
    id_column,
    symbols,
    timeframe,
):
    ranked = (
        db.query(
            id_column.label("record_id"),
            func.row_number()
            .over(partition_by=symbol_column, order_by=id_column.desc())
            .label("row_number"),
        )
        .filter(symbol_column.in_(symbols), timeframe_column == timeframe)
        .subquery()
    )
    rows = (
        db.query(model)
        .join(ranked, id_column == ranked.c.record_id)
        .filter(ranked.c.row_number == 1)
        .all()
    )
    return {str(getattr(row, symbol_column.key)).upper(): row for row in rows}


def _session_cache(db, key):
    info = getattr(db, "info", None)
    if not isinstance(info, dict):
        return None

    return info.setdefault(key, {})
