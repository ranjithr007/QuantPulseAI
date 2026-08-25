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
        results = []
        errors = []
        expected_count = len(symbols) * len(TIMEFRAMES)
        for item in symbols:

            symbol = item.symbol

            for tf in TIMEFRAMES:
                try:
                    result = generate_orderflow(symbol, tf, context=context)
                    if result is None:
                        errors.append(
                            {
                                "symbol": symbol,
                                "timeframe": tf,
                                "error": "Orderflow engine returned no result",
                            }
                        )
                    else:
                        results.append(result)
                    # print(symbol, tf, result)
                except Exception as ex:
                    error = summarize_network_error(ex)
                    errors.append(
                        {
                            "symbol": symbol,
                            "timeframe": tf,
                            "error": error,
                        }
                    )
                    if not is_transient_network_error(ex):
                        print(
                            f"Orderflow job error {symbol} {tf}: {error}"
                        )
                    continue
        completed_count = len(results)
        return {
            "source": "orderflow_job",
            "status": (
                "OK"
                if completed_count == expected_count
                else "DEGRADED"
                if completed_count
                else "FAILED"
            ),
            "expected_count": expected_count,
            "processed_count": expected_count,
            "saved_count": completed_count,
            "failed_count": len(errors),
            "rows_written": completed_count,
            "results": results,
            "errors": errors,
        }
    except Exception as ex:
        safe_rollback(db)
        error = summarize_network_error(ex)
        if not is_transient_network_error(ex):
            print("Orderflow job error:", error)
        return {
            "source": "orderflow_job",
            "status": "FAILED",
            "expected_count": 0,
            "processed_count": 0,
            "saved_count": 0,
            "failed_count": 1,
            "rows_written": 0,
            "results": [],
            "errors": [{"error": error}],
        }

    finally:

        db.close()
