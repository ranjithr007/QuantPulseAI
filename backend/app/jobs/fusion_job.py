from app.database.sqlserver import SessionLocal

from app.repositories.symbol_repository import SymbolRepository
from app.services.fusion_service import FusionService
from app.repositories._db_utils import safe_rollback
from app.utils.network_resilience import is_transient_network_error
from app.utils.network_resilience import summarize_network_error
from app.governance.evidence_policy import OFFICIAL_ENTRY_TIMEFRAMES

service = FusionService()
TIMEFRAMES = list(OFFICIAL_ENTRY_TIMEFRAMES)

def run_fusion_job(*, context=None):

    print("Running Fusion signal Collector...")
    db = SessionLocal()
    try:
        symbols = [
            str(item.symbol).strip().upper()
            for item in SymbolRepository().get_active_symbols(db)
        ]
        # Fusion reads its own evidence through the service.  Release the
        # symbol lookup transaction before iterating over all provider/timeframe
        # combinations so this job cannot hold a pool slot for the full cycle.
        safe_rollback(db)
        results=[]
        for symbol in symbols:
            for timeframe in TIMEFRAMES:
                try:
                    result = service.generate(db, symbol, timeframe, context=context)
                    results.append(result)
                except Exception as ex:
                    if not is_transient_network_error(ex):
                        print(
                            f"Fusion job error {symbol} {timeframe}: {summarize_network_error(ex)}"
                        )
                    continue
        return results
    except Exception as e:

        if not is_transient_network_error(e):
            print("Fusion Job Error:", summarize_network_error(e))

        safe_rollback(db)

    finally:

        db.close()
