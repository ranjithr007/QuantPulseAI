from app.features.feature_service import generate_features
from app.database.sqlserver import SessionLocal
from app.repositories.symbol_repository import SymbolRepository
from app.repositories._db_utils import safe_rollback
from app.utils.network_resilience import classify_network_error
from app.utils.network_resilience import is_transient_network_error


TIMEFRAMES = ["5m", "15m", "1h", "4h", "1d"]


def run_feature_job():

    print("Running Feature Factory...")

    db = SessionLocal()

    try:
        symbol_repo = SymbolRepository()
        symbols = symbol_repo.get_active_symbols(db)
        for item in symbols:
            for tf in TIMEFRAMES:
                try:
                    generate_features(item.symbol, tf)
                except Exception as ex:
                    if not is_transient_network_error(ex):
                        print(f"Feature job error {item.symbol} {tf}: {classify_network_error(ex)}")
                    continue
    except Exception as ex:
        safe_rollback(db)
        if not is_transient_network_error(ex):
            print("Feature job error:", classify_network_error(ex))
    finally:
        db.close()
