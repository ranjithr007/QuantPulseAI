from app.database.sqlserver import SessionLocal

from app.repositories.symbol_repository import SymbolRepository

from app.engines.whale_engine import WhaleEngine

from app.repositories.whale_signal_repository import WhaleSignalRepository
from app.repositories._db_utils import safe_rollback
from app.utils.network_resilience import is_transient_network_error
from app.utils.network_resilience import summarize_network_error


def run_whale_intelligence_job():

    print("Running Whale Intelligence")

    db = SessionLocal()
    try:
        symbols = SymbolRepository().get_active_symbols(db)

        for item in symbols:
            try:
                result = WhaleEngine().analyze(db, item.symbol)

                # print(result)

                WhaleSignalRepository().save(db, result)
            except Exception as ex:
                if not is_transient_network_error(ex):
                    print(
                        f"Whale intelligence job error {item.symbol}: {summarize_network_error(ex)}"
                    )
                continue
    except Exception as ex:
        safe_rollback(db)
        if not is_transient_network_error(ex):
            print("Whale intelligence job error:", summarize_network_error(ex))
    finally:
        db.close()
