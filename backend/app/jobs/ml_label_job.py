from app.database.sqlserver import SessionLocal

from app.repositories.symbol_repository import SymbolRepository

from app.ml.label_generator import LabelGenerator
from app.repositories._db_utils import safe_rollback
from app.utils.network_resilience import is_transient_network_error
from app.utils.network_resilience import summarize_network_error


def run_ml_label_job():

    db = SessionLocal()

    try:
        symbols = SymbolRepository().get_active_symbols(db)

        for item in symbols:
            try:
                result = LabelGenerator(db).generate(item.symbol)

                print(f"ML labels generated for {item.symbol}: {result}")
            except Exception as ex:
                if not is_transient_network_error(ex):
                    print(
                        f"ML label generation failed for {item.symbol}: {summarize_network_error(ex)}"
                    )
                continue
    except Exception as ex:

        safe_rollback(db)

        if not is_transient_network_error(ex):
            print(f"ML label generation failed : {summarize_network_error(ex)}")

        raise
    finally:

        db.close()
