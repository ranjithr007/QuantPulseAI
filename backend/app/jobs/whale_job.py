from app.database.sqlserver import SessionLocal

from app.repositories.symbol_repository import SymbolRepository

from app.collectors.binances.whale_collector import WhaleCollector

from app.repositories.whale_repository import WhaleRepository
from app.repositories.orderflow_repository import OrderFlowRepository
from app.engines.orderflow_engine import OrderFlowEngine
from app.repositories._db_utils import safe_rollback
from app.utils.network_resilience import is_transient_network_error
from app.utils.network_resilience import summarize_network_error


def run_whale_job():

    print("Running Whale Engine")

    db = SessionLocal()

    try:
        symbols = SymbolRepository().get_active_symbols(db)
        collector = WhaleCollector()
        repo = WhaleRepository()
        order_repo = OrderFlowRepository()
        engine = OrderFlowEngine()
        processed_symbols = []
        skipped_symbols = []
        failed_symbols = []

        for item in symbols:
            try:
                trades = collector.get_order_flow(item.symbol)

                if not trades:
                    print("No whale data:", item.symbol)
                    skipped_symbols.append(item.symbol)
                    continue
                # print(trades)
                repo.save_many(db, trades["whales"])

                previous_cvd = order_repo.get_last_cvd(db, item.symbol)
                trades["cumulative_delta"] = previous_cvd + trades["delta"]
                history = order_repo.get_recent_flow(db, item.symbol)

                abs_type, abs_strength = engine.detect_absorption(trades)

                trades["absorption_type"] = abs_type

                trades["absorption_strength"] = abs_strength

                ex_type, ex_strength = engine.detect_exhaustion(trades, history)

                trades["exhaustion_type"] = ex_type

                trades["exhaustion_strength"] = ex_strength

                order_repo.save(db, trades)
                processed_symbols.append(item.symbol)
            except Exception as ex:
                safe_rollback(db)
                failed_symbols.append(item.symbol)
                if not is_transient_network_error(ex):
                    print(
                        f"Whale job error {item.symbol}: "
                        f"{summarize_network_error(ex)}"
                    )
                continue

        return {
            "status": "DEGRADED" if failed_symbols else "OK",
            "source": "whale_job",
            "symbols": len(symbols),
            "processed": processed_symbols,
            "skipped": skipped_symbols,
            "failed": failed_symbols,
        }

    except Exception as ex:

        safe_rollback(db)

        if not is_transient_network_error(ex):
            print("Whale job error:", summarize_network_error(ex))

        return {
            "status": "DEGRADED",
            "source": "whale_job",
            "error": summarize_network_error(ex),
        }

    finally:

        db.close()
