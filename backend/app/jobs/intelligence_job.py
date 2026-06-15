from app.database.sqlserver import SessionLocal

from app.repositories.symbol_repository import SymbolRepository

from app.features.market_feature_builder import MarketFeatureBuilder

from app.engines.liquidity_engine import LiquidityEngine

from app.repositories.liquidity_repository import LiquidityRepository


def run_intelligence_job():

    print("Running AI Intelligence...")

    db = SessionLocal()

    symbols = SymbolRepository().get_active_symbols(db)

    for item in symbols:

        symbol = item.symbol

        features = MarketFeatureBuilder().build(db, symbol)

        if not features:

            continue
        
        # print("FEATURES:", features)
        result = LiquidityEngine().analyze(
            symbol, features["funding"], features["oi_change"], features["price_change"]
        )
        LiquidityRepository().save(db, result)

        # print(result)

    db.close()