from app.database.sqlserver import SessionLocal
from app.repositories.symbol_repository import SymbolRepository
from app.orderflow.orderflow_service import generate_orderflow


TIMEFRAMES = ["5m", "15m", "1h", "4h", "1d"]


def run_orderflow_job():

    print("🔥 Running OrderFlow Engine...")

    db = SessionLocal()

    try:

        symbols = SymbolRepository().get_active_symbols(db)

        for item in symbols:

            symbol = item.symbol

            for tf in TIMEFRAMES:

                result = generate_orderflow(symbol, tf)

                # print(symbol, tf, result)

    finally:

        db.close()
