from app.database.sqlserver import SessionLocal
from app.repositories.symbol_repository import SymbolRepository
from app.orderflow.orderflow_service import generate_orderflow
from app.repositories._db_utils import safe_rollback
from app.utils.network_resilience import is_transient_network_error
from app.utils.network_resilience import summarize_network_error
from app.governance.evidence_policy import OFFICIAL_ENTRY_TIMEFRAMES


TIMEFRAMES = list(OFFICIAL_ENTRY_TIMEFRAMES)


def run_orderflow_job(*, context=None):

    print("Running OrderFlow Engine...")

    db = SessionLocal()

    try:

        symbols = SymbolRepository().get_active_symbols(db)
        results=[]
        for item in symbols:

            symbol = item.symbol

            for tf in TIMEFRAMES:
                try:
                    result = generate_orderflow(symbol, tf, context=context)
                    results.append(result)
                    # print(symbol, tf, result)
                except Exception as ex:
                    if not is_transient_network_error(ex):
                        print(
                            f"Orderflow job error {symbol} {tf}: {summarize_network_error(ex)}"
                        )
                    continue
        return results
    except Exception as ex:
        safe_rollback(db)
        if not is_transient_network_error(ex):
            print("Orderflow job error:", summarize_network_error(ex))

    finally:

        db.close()
