from app.database.sqlserver import SessionLocal

from app.repositories.symbol_repository import SymbolRepository

from app.collectors.binances.funding_collector import FundingCollector

from app.collectors.binances.open_interest_collector import OpenInterestCollector

from app.repositories.derivative_repository import DerivativeRepository


def run_derivative_job():

    print("Running Derivative Collector")

    db = SessionLocal()

    symbols = SymbolRepository().get_active_symbols(db)

    repo = DerivativeRepository()

    for s in symbols:

        funding = FundingCollector().get_funding(s.symbol)

        oi = OpenInterestCollector().get_data(s.symbol)

        repo.save_funding(db, funding)

        repo.save_open_interest(db, oi)

    db.close()