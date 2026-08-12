from app.database.sqlserver import SessionLocal

from app.repositories.symbol_repository import SymbolRepository

from app.collectors.binances.funding_collector import FundingCollector

from app.collectors.binances.open_interest_collector import OpenInterestCollector
from app.collectors.binances.mark_price_collector import MarkPriceCollector
from app.collectors.binances.leverage_bracket_collector import LeverageBracketCollector
from app.repositories.derivative_repository import DerivativeRepository
from app.repositories._db_utils import safe_rollback
from app.governance.evidence_policy import OFFICIAL_ENTRY_TIMEFRAMES
from app.utils.network_resilience import is_transient_network_error
from app.utils.network_resilience import summarize_network_error

def run_derivative_job():
    print("Running Derivative Collector")
    db = SessionLocal()
    results=[]
    try:
        symbols = SymbolRepository().get_active_symbols(db)
        repo = DerivativeRepository()
        bracket_collector = LeverageBracketCollector()
        for s in symbols:
            funding = FundingCollector().get_funding(s.symbol)
            oi = OpenInterestCollector().get_data(s.symbol)
            mark_prices = []
            margin_brackets = bracket_collector.get_brackets(s.symbol)
            for timeframe in OFFICIAL_ENTRY_TIMEFRAMES:
                mark_prices.extend(
                    MarkPriceCollector().get_klines(
                        s.symbol,
                        timeframe,
                        limit=2,
                    )
                )
            if funding is not None:
                repo.save_funding(db, funding)
                results.append(funding) 
            if oi is not None:
                repo.save_open_interest(db, oi)
                results.append(oi)
            if mark_prices:
                repo.save_mark_prices(db, mark_prices)
                results.extend(mark_prices)
            if margin_brackets:
                repo.save_margin_brackets(db, margin_brackets)
                results.extend(margin_brackets)
        return results
    except Exception as ex:
        safe_rollback(db)
        if not is_transient_network_error(ex):
            print("Derivative job error:", summarize_network_error(ex))
    finally:
        db.close()
