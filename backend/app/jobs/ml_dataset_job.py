import datetime
from app.database.sqlserver import SessionLocal

from app.repositories.symbol_repository import SymbolRepository
from app.ml.dataset_builder import DatasetBuilder
from app.repositories._db_utils import safe_rollback
from app.utils.network_resilience import is_transient_network_error
from app.utils.network_resilience import summarize_network_error


def run_ml_dataset_job():

    db = SessionLocal()
    try:
        print("ML dataset job started", datetime.datetime.now())
        SYMBOLS = SymbolRepository().get_active_symbols(db)
        builder = DatasetBuilder(db)

        for item in SYMBOLS:
            try:
                symbol = item.symbol
                builder.build(
                    symbol=symbol, timeframe="5m"
                )  # Need to build for 1m timeframe to have more data points for training
            except Exception as ex:
                if not is_transient_network_error(ex):
                    print(f"ML dataset job error {item.symbol}: {summarize_network_error(ex)}")
                continue

        print(builder.build(symbol="BTCUSDT", timeframe="5m"))
        print("ML dataset completed", datetime.datetime.now())

    except Exception as ex:
        safe_rollback(db)
        if not is_transient_network_error(ex):
            print(f"ML dataset job error: {summarize_network_error(ex)}")
    finally:

        db.close()
