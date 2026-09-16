from concurrent.futures import ThreadPoolExecutor
from time import monotonic

from app.database.sqlserver import SessionLocal

from app.collectors.binances.candle_collector import CandleCollector
from app.collectors.Bybit.candle_collector import (
    CandleCollector as BybitCandleCollector,
)

from app.governance.evidence_policy import OFFICIAL_ENTRY_TIMEFRAMES
from app.paper_trading.exit_policy import PAPER_EXIT_MONITOR_TIMEFRAME
from app.market_data.incremental_fetch import plan_incremental_fetch
from app.market_data.quality import analyze_candle_sequence
from app.repositories.market_repository import MarketRepository
from app.repositories.symbol_repository import SymbolRepository
from app.utils.network_resilience import classify_network_error
from app.utils.network_resilience import is_transient_network_error

TIMEFRAMES = [PAPER_EXIT_MONITOR_TIMEFRAME, *OFFICIAL_ENTRY_TIMEFRAMES]
EXIT_MONITOR_BOOTSTRAP_CANDLES = 600
MARKET_FETCH_WORKERS = 8
MARKET_PROVIDER_TIMEOUT_SECONDS = 5
MARKET_PROVIDER_MAX_ATTEMPTS = 1


def run_market_job():
    print("Running Market Collector...")
    started = monotonic()

    db = SessionLocal()

    total_fetched = 0
    total_saved = 0
    total_skipped = 0
    total_failed = 0

    results = []

    try:
        symbol_repo = SymbolRepository()
        collector = CandleCollector(
            timeout_seconds=MARKET_PROVIDER_TIMEOUT_SECONDS,
            max_attempts=MARKET_PROVIDER_MAX_ATTEMPTS,
        )
        fallback_collector = BybitCandleCollector(
            timeout_seconds=MARKET_PROVIDER_TIMEOUT_SECONDS,
            max_attempts=MARKET_PROVIDER_MAX_ATTEMPTS,
        )
        repo = MarketRepository()
        symbols = symbol_repo.get_active_symbols(db)
        planned = []
        for symbol in symbols:
            symbol_name = symbol.symbol
            for timeframe in TIMEFRAMES:
                try:
                    latest_candle_cursor = repo.get_collection_cursor(
                        db,
                        symbol_name,
                        timeframe,
                    )
                    fetch_plan = plan_incremental_fetch(
                        latest_candle_cursor,
                        timeframe,
                        bootstrap_limit=(
                            EXIT_MONITOR_BOOTSTRAP_CANDLES
                            if timeframe == PAPER_EXIT_MONITOR_TIMEFRAME
                            else 3
                        ),
                    )
                    if not fetch_plan.should_fetch:
                        planned.append(
                            {
                                "kind": "result",
                                "symbol": symbol_name,
                                "timeframe": timeframe,
                                "source": "BINANCE_FUTURES",
                                "fetched": 0,
                                "saved": 0,
                                "skipped": 0,
                                "fetch_plan": fetch_plan.as_dict(),
                                "quality": {
                                    "status": "NOT_DUE",
                                    "issues": [],
                                },
                                "last_saved_candle": None,
                            }
                        )
                        continue
                    planned.append(
                        {
                            "kind": "fetch",
                            "symbol": symbol_name,
                            "timeframe": timeframe,
                            "fetch_plan": fetch_plan,
                        }
                    )
                except Exception as ex:
                    db.rollback()
                    total_failed += 1
                    error_message = classify_network_error(ex)
                    planned.append(
                        {
                            "kind": "result",
                            "symbol": symbol_name,
                            "timeframe": timeframe,
                            "source": "BINANCE_FUTURES",
                            "status": "FAILED",
                            "fetched": 0,
                            "saved": 0,
                            "skipped": 0,
                            "error": error_message,
                        }
                    )
                    if not is_transient_network_error(ex):
                        print(
                            f"Market job error "
                            f"{symbol_name} {timeframe}: "
                            f"{error_message}"
                        )

        # Planning is read-only. Release its transaction before waiting on
        # external providers so slow Binance/Bybit retries cannot retain SQL
        # Server locks and make unrelated dashboard reads appear offline.
        db.rollback()

        fetch_items = [item for item in planned if item["kind"] == "fetch"]
        futures = {}
        if fetch_items:
            executor = ThreadPoolExecutor(
                max_workers=min(MARKET_FETCH_WORKERS, len(fetch_items))
            )
            futures = {
                id(item): executor.submit(
                    _fetch_market_candles,
                    collector,
                    fallback_collector,
                    item["symbol"],
                    item["timeframe"],
                    item["fetch_plan"],
                )
                for item in fetch_items
            }
        else:
            executor = None

        try:
            for item in planned:
                if item["kind"] == "result":
                    results.append(
                        {key: value for key, value in item.items() if key != "kind"}
                    )
                    continue

                symbol_name = item["symbol"]
                timeframe = item["timeframe"]
                fetch_plan = item["fetch_plan"]
                source = "BINANCE_FUTURES"
                fetched_count = 0
                saved_count = 0
                skipped_count = 0
                latest_candle = None
                try:
                    source, candles = futures[id(item)].result()
                    candles = candles or []
                    if not candles:
                        total_failed += 1
                        results.append(
                            {
                                "symbol": symbol_name,
                                "timeframe": timeframe,
                                "source": source,
                                "status": "FAILED",
                                "fetched": 0,
                                "saved": 0,
                                "skipped": 0,
                                "fetch_plan": fetch_plan.as_dict(),
                                "error": "NO_CANDLES_FROM_AVAILABLE_SOURCES",
                            }
                        )
                        continue

                    fetched_count = len(candles)
                    total_fetched += fetched_count
                    for candle in candles:
                        inserted = repo.save_candle(db, candle)
                        if inserted:
                            saved_count += 1
                            total_saved += 1
                            latest_candle = candle
                        else:
                            skipped_count += 1
                            total_skipped += 1

                    results.append(
                        {
                            "symbol": symbol_name,
                            "timeframe": timeframe,
                            "source": source,
                            "fetched": fetched_count,
                            "saved": saved_count,
                            "skipped": skipped_count,
                            "fetch_plan": fetch_plan.as_dict(),
                            "quality": analyze_candle_sequence(
                                candles,
                                timeframe,
                                allow_trailing_provisional=True,
                            ),
                            "last_saved_candle": (
                                {
                                    "open_time_ms": latest_candle.get("open_time_ms"),
                                    "open": latest_candle.get("open"),
                                    "high": latest_candle.get("high"),
                                    "low": latest_candle.get("low"),
                                    "close": latest_candle.get("close"),
                                    "volume": latest_candle.get("volume"),
                                }
                                if latest_candle
                                else None
                            ),
                        }
                    )
                except Exception as ex:
                    db.rollback()
                    total_failed += 1
                    error_message = classify_network_error(ex)
                    results.append(
                        {
                            "symbol": symbol_name,
                            "timeframe": timeframe,
                            "source": source,
                            "fetched": fetched_count,
                            "saved": saved_count,
                            "skipped": skipped_count,
                            "fetch_plan": fetch_plan.as_dict(),
                            "error": error_message,
                        }
                    )
                    if not is_transient_network_error(ex):
                        print(
                            f"Market job error "
                            f"{symbol_name} {timeframe}: "
                            f"{error_message}"
                        )
        finally:
            if executor is not None:
                executor.shutdown(wait=True, cancel_futures=True)

        print("\nMarket data collection completed")

        return {
            "source": "market_collector",
            "status": "FAILED" if total_failed else "COMPLETED",
            "active_symbols": len(symbols),
            "timeframes": len(TIMEFRAMES),
            "processed_combinations": len(results),
            "total_fetched": total_fetched,
            "total_saved": total_saved,
            "rows_written": total_saved,
            "total_skipped": total_skipped,
            "total_failed": total_failed,
            "duration_seconds": round(monotonic() - started, 3),
            "fetch_workers": MARKET_FETCH_WORKERS,
            "results": results,
        }

    except Exception as ex:
        db.rollback()

        error_message = classify_network_error(ex)

        if not is_transient_network_error(ex):
            print("Market job error:", error_message)

        return {
            "source": "market_collector",
            "status": "failed",
            "error": error_message,
            "total_fetched": total_fetched,
            "total_saved": total_saved,
            "rows_written": total_saved,
            "total_skipped": total_skipped,
            "total_failed": total_failed + 1,
            "duration_seconds": round(monotonic() - started, 3),
            "fetch_workers": MARKET_FETCH_WORKERS,
            "results": results,
        }

    finally:
        db.close()


def _fetch_market_candles(
    collector,
    fallback_collector,
    symbol,
    timeframe,
    fetch_plan,
):
    options = {
        "interval": timeframe,
        "limit": fetch_plan.limit,
        "start_time_ms": fetch_plan.start_time_ms,
        "end_time_ms": fetch_plan.end_time_ms,
    }
    candles = collector.get_candles(symbol, **options)
    if candles:
        return "BINANCE_FUTURES", candles
    return "BYBIT", fallback_collector.get_candles(symbol, **options)
