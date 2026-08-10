from app.features.feature_service import generate_features
from app.database.sqlserver import SessionLocal
from app.repositories.symbol_repository import SymbolRepository
from app.repositories._db_utils import safe_rollback
from app.utils.network_resilience import classify_network_error
from app.utils.network_resilience import is_transient_network_error
from app.governance.evidence_policy import OFFICIAL_ENTRY_TIMEFRAMES
TIMEFRAMES = list(OFFICIAL_ENTRY_TIMEFRAMES)

def run_feature_job(*, context=None):
    print("Running Feature Factory...")
    db = SessionLocal()
    try:
        symbol_repo = SymbolRepository()
        symbols = symbol_repo.get_active_symbols(db)
        results=[]
        for item in symbols:
            for tf in TIMEFRAMES:
                try:
                    result= generate_features(item.symbol, tf, context=context)
                    results.append(result)
                except Exception as ex:
                    if not is_transient_network_error(ex):
                        print(f"Feature job error {item.symbol} {tf}: {classify_network_error(ex)}")
                    continue
        return results
    except Exception as ex:
        safe_rollback(db)
        if not is_transient_network_error(ex):
            print("Feature job error:", classify_network_error(ex))
        
    finally:
        db.close()
        
