from app.database.sqlserver import SessionLocal

from app.repositories.symbol_repository import SymbolRepository

from app.engines.whale_engine import WhaleEngine

from app.repositories.whale_signal_repository import WhaleSignalRepository


def run_whale_intelligence_job():

    print("Running Whale Intelligence")

    db = SessionLocal()

    symbols = SymbolRepository().get_active_symbols(db)

    for item in symbols:

        result = WhaleEngine().analyze(db, item.symbol)

        # print(result)

        WhaleSignalRepository().save(db, result)

    db.close()