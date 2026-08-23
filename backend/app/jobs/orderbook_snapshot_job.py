from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import as_completed

from app.collectors.binances.orderbook_collector import OrderBookCollector
from app.database.sqlserver import SessionLocal
from app.repositories.orderbook_snapshot_repository import OrderBookSnapshotRepository
from app.repositories.symbol_repository import SymbolRepository
from app.repositories._db_utils import safe_rollback
from app.utils.network_resilience import summarize_network_error


def run_orderbook_snapshot_job():
    db = SessionLocal()
    try:
        symbols = [item.symbol for item in SymbolRepository().get_active_symbols(db)]
        collector = OrderBookCollector()
        collected = []
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = {
                executor.submit(collector.get_snapshot, symbol): symbol
                for symbol in symbols
            }
            for future in as_completed(futures):
                payload = future.result()
                if payload is not None:
                    collected.append(payload)
        repository = OrderBookSnapshotRepository()
        for payload in collected:
            repository.save(db, payload)
        return {
            "status": "OK" if len(collected) == len(symbols) else "DEGRADED",
            "source": "orderbook_snapshot_job",
            "symbols": len(symbols),
            "stored": len(collected),
        }
    except Exception as exc:
        safe_rollback(db)
        return {
            "status": "DEGRADED",
            "source": "orderbook_snapshot_job",
            "error": summarize_network_error(exc),
        }
    finally:
        db.close()
