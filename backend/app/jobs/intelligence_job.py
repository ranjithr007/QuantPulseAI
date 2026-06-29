from app.database.sqlserver import SessionLocal

from app.repositories.symbol_repository import SymbolRepository

from app.features.market_feature_builder import MarketFeatureBuilder

from app.engines.liquidity_engine import LiquidityEngine

from app.repositories.liquidity_repository import LiquidityRepository
from app.repositories._db_utils import safe_rollback
from app.utils.network_resilience import classify_network_error
from app.utils.network_resilience import is_transient_network_error


def run_intelligence_job():

    print("Running AI Intelligence...")

    db = SessionLocal()
    try:
        symbols = SymbolRepository().get_active_symbols(db)
        results=[]
        for item in symbols:
            try:
                symbol = item.symbol
                features = MarketFeatureBuilder().build(db, symbol)
                if not features:
                    continue                
                # print("FEATURES:", features)
                result = LiquidityEngine().analyze(
                    symbol, features["funding"], features["oi_change"], features["price_change"]
                )
                LiquidityRepository().save(db, result)
                results.append(result)
                # print(result)
            except Exception as ex:
                if not is_transient_network_error(ex):
                    print(f"Intelligence job error {item.symbol}: {classify_network_error(ex)}")
                continue
        return results
    except Exception as ex:
        safe_rollback(db)
        if not is_transient_network_error(ex):
            print("Intelligence job error:", classify_network_error(ex))
    finally:
        db.close()
