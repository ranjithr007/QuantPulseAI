from app.database.sqlserver import SessionLocal

from app.repositories.symbol_repository import SymbolRepository
from app.services.fusion_service import FusionService

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
                result = service.generate(db, symbol, timeframe)
                # print(f"Fusion saved: {symbol} [{timeframe}]", result.decision)
            # print("Fusion AI saved:", symbol, result.decision, result.confidence)

    except Exception as e:

        print("Fusion Job Error:", e)

        db.rollback()

    finally:

        db.close()