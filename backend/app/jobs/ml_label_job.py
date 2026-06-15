from app.database.sqlserver import SessionLocal

from app.repositories.symbol_repository import SymbolRepository

from app.ml.label_generator import LabelGenerator


def run_ml_label_job():

    db = SessionLocal()
    symbols = SymbolRepository().get_active_symbols(db)

    try:
        for item in symbols:
            result = LabelGenerator(db).generate(item.symbol)

            print(f"ML labels generated for {item.symbol}: {result}")
    except Exception as ex:

        db.rollback()

        print(f"ML label generation failed : {ex}")

        raise
    finally:

        db.close()