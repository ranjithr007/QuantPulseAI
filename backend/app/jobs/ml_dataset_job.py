import datetime
from app.database.sqlserver import SessionLocal

from app.repositories.symbol_repository import SymbolRepository
from app.ml.dataset_builder import DatasetBuilder


def run_ml_dataset_job():

    db = SessionLocal()
    print("ML dataset job started", datetime.datetime.now())
    try:
        SYMBOLS = SymbolRepository().get_active_symbols(db)
        builder = DatasetBuilder(db)

        for item in SYMBOLS:

            symbol = item.symbol
            builder.build(
                symbol=symbol, timeframe="5m"
            )  # Need to build for 1m timeframe to have more data points for training

        print(builder.build(symbol="BTCUSDT", timeframe="5m"))
        print("ML dataset completed", datetime.datetime.now())

    finally:

        db.close()