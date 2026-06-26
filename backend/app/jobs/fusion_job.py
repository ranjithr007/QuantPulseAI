from app.database.sqlserver import SessionLocal

from app.repositories.symbol_repository import SymbolRepository
from app.services.fusion_service import FusionService
from app.repositories._db_utils import safe_rollback
from app.utils.network_resilience import is_transient_network_error
from app.utils.network_resilience import summarize_network_error

service = FusionService()
TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"]

def run_fusion_job():

    print("Running Fusion signal Collector...")

    db = SessionLocal()

    try:

        symbols = SymbolRepository().get_active_symbols(db)

        for item in symbols: 
            symbol = item.symbol
            for timeframe in TIMEFRAMES:
                try:
                    result = service.generate(db, symbol, timeframe)
                    # print(f"Fusion saved: {symbol} [{timeframe}]", result.decision)
                except Exception as ex:
                    if not is_transient_network_error(ex):
                        print(
                            f"Fusion job error {symbol} {timeframe}: {summarize_network_error(ex)}"
                        )
                    continue
            # print("Fusion AI saved:", symbol, result.decision, result.confidence)

    except Exception as e:

        if not is_transient_network_error(e):
            print("Fusion Job Error:", summarize_network_error(e))

        safe_rollback(db)

    finally:

        db.close()
