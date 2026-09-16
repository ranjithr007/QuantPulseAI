from concurrent.futures import ThreadPoolExecutor

from app.database.sqlserver import SessionLocal

from app.repositories.symbol_repository import SymbolRepository

from app.collectors.binances.funding_collector import FundingCollector

from app.collectors.binances.open_interest_collector import OpenInterestCollector
from app.collectors.binances.mark_price_collector import MarkPriceCollector
from app.collectors.binances.leverage_bracket_collector import LeverageBracketCollector
from app.repositories.derivative_repository import DerivativeRepository
from app.repositories._db_utils import safe_rollback
from app.governance.evidence_policy import OFFICIAL_ENTRY_TIMEFRAMES
from app.paper_trading.exit_policy import PAPER_EXIT_MONITOR_TIMEFRAME
from app.utils.network_resilience import is_transient_network_error
from app.utils.network_resilience import summarize_network_error

DERIVATIVE_FETCH_WORKERS = 6
DERIVATIVE_PROVIDER_TIMEOUT_SECONDS = 5
DERIVATIVE_PROVIDER_MAX_ATTEMPTS = 1


def run_derivative_job():
    print("Running Derivative Collector")
    db = SessionLocal()
    results=[]
    try:
        symbols = SymbolRepository().get_active_symbols(db)
        repo = DerivativeRepository()
        normalized_symbols = [item.symbol for item in symbols]

        # The symbol lookup is read-only. End that transaction before waiting
        # on Binance so provider latency cannot retain SQL Server locks and
        # block independent dashboard/history reads.
        safe_rollback(db)

        collected = {}
        with ThreadPoolExecutor(
            max_workers=min(
                DERIVATIVE_FETCH_WORKERS,
                max(1, len(normalized_symbols)),
            )
        ) as executor:
            futures = {
                symbol: executor.submit(_collect_symbol_derivatives, symbol)
                for symbol in normalized_symbols
            }
            for symbol in normalized_symbols:
                try:
                    collected[symbol] = futures[symbol].result()
                except Exception as ex:
                    if not is_transient_network_error(ex):
                        print(
                            f"Derivative job error {symbol}: "
                            f"{summarize_network_error(ex)}"
                        )

        # All external calls have completed before database persistence begins.
        # This prevents a write/read transaction from remaining open while a
        # slower symbol future is still pending.
        for symbol in normalized_symbols:
            payload = collected.get(symbol)
            if payload is None:
                continue
            funding, oi, mark_prices, margin_brackets = payload

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


def _collect_symbol_derivatives(symbol):
    funding = FundingCollector(
        timeout_seconds=DERIVATIVE_PROVIDER_TIMEOUT_SECONDS,
        max_attempts=DERIVATIVE_PROVIDER_MAX_ATTEMPTS,
    ).get_funding(symbol)
    open_interest = OpenInterestCollector(
        timeout_seconds=DERIVATIVE_PROVIDER_TIMEOUT_SECONDS,
        max_attempts=DERIVATIVE_PROVIDER_MAX_ATTEMPTS,
    ).get_data(symbol)
    margin_brackets = LeverageBracketCollector(
        timeout_seconds=DERIVATIVE_PROVIDER_TIMEOUT_SECONDS,
    ).get_brackets(symbol)
    mark_collector = MarkPriceCollector(
        timeout_seconds=DERIVATIVE_PROVIDER_TIMEOUT_SECONDS,
        max_attempts=DERIVATIVE_PROVIDER_MAX_ATTEMPTS,
    )
    mark_prices = []
    for timeframe in (
        PAPER_EXIT_MONITOR_TIMEFRAME,
        *OFFICIAL_ENTRY_TIMEFRAMES,
    ):
        mark_prices.extend(
            mark_collector.get_klines(symbol, timeframe, limit=2)
        )
    return funding, open_interest, mark_prices, margin_brackets
