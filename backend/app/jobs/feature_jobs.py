from app.features.feature_service import generate_features
from app.database.sqlserver import SessionLocal
from app.repositories.symbol_repository import SymbolRepository


TIMEFRAMES = ["5m", "15m", "1h", "4h", "1d"]


def run_feature_job():

    print("Running Feature Factory...")

    db = SessionLocal()
    symbol_repo = SymbolRepository()

    symbols = symbol_repo.get_active_symbols(db)
    for item in symbols:

        for tf in TIMEFRAMES:

            result = generate_features(item.symbol, tf)

            # print(result)
