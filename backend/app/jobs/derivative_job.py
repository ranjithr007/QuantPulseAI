from app.database.sqlserver import SessionLocal

from app.repositories.symbol_repository import SymbolRepository

from app.collectors.binances.funding_collector import FundingCollector

from app.collectors.binances.open_interest_collector import OpenInterestCollector

from app.repositories.derivative_repository import DerivativeRepository
from app.repositories._db_utils import safe_rollback
from app.utils.network_resilience import is_transient_network_error
from app.utils.network_resilience import summarize_network_error


def run_derivative_job():
    print("Running Derivative Collector")

    db = SessionLocal()

    try:
        symbols = SymbolRepository().get_active_symbols(db)
        repo = DerivativeRepository()

        for s in symbols:
            funding = FundingCollector().get_funding(s.symbol)
            oi = OpenInterestCollector().get_data(s.symbol)

            if funding is not None:
                repo.save_funding(db, funding)

            if oi is not None:
                repo.save_open_interest(db, oi)
    except Exception as ex:
        safe_rollback(db)
        if not is_transient_network_error(ex):
            print("Derivative job error:", summarize_network_error(ex))
    finally:
        db.close()
