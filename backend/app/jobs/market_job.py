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


def run_market_job():
    print("Running Market Collector...")

    db = SessionLocal()

    total_fetched = 0
    total_saved = 0
    total_skipped = 0
    total_failed = 0

    results = []

    try:
        symbol_repo = SymbolRepository()
        collector = CandleCollector()
        fallback_collector = BybitCandleCollector()
        repo = MarketRepository()
        symbols = symbol_repo.get_active_symbols(db)
        # print("Active symbols:", len(symbols))
        for symbol in symbols:
            symbol_name = symbol.symbol
            for timeframe in TIMEFRAMES:
                fetched_count = 0
                saved_count = 0
                skipped_count = 0
                source = "BINANCE_FUTURES"
                latest_candle = None
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
                        results.append(
                            {
                                "symbol": symbol_name,
                                "timeframe": timeframe,
                                "source": source,
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

                    candles = collector.get_candles(
                        symbol_name,
                        interval=timeframe,
                        limit=fetch_plan.limit,
                        start_time_ms=fetch_plan.start_time_ms,
                        end_time_ms=fetch_plan.end_time_ms,
                    )

                    if not candles:
                        source = "BYBIT"

                        candles = fallback_collector.get_candles(
                            symbol_name,
                            interval=timeframe,
                            limit=fetch_plan.limit,
                            start_time_ms=fetch_plan.start_time_ms,
                            end_time_ms=fetch_plan.end_time_ms,
                        )

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

                    result = {
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

                    results.append(result)

                    # print("\nMARKET DATA RESULT")
                    # print("Symbol:", symbol_name)
                    # print("Timeframe:", timeframe)
                    # print("Source:", source)
                    # print("Fetched:", fetched_count)
                    # print("Saved:", saved_count)
                    # print("Skipped existing:", skipped_count)

                    # if latest_candle:
                    #     print(
                    #         "Latest saved candle:",
                    #         result["last_saved_candle"],
                    #     )
                    # else:
                    #     print(
                    #         "Latest saved candle: None "
                    #         "(all candles may already exist)"
                    #     )

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
                            "error": error_message,
                        }
                    )

                    if not is_transient_network_error(ex):
                        print(
                            f"Market job error "
                            f"{symbol_name} {timeframe}: "
                            f"{error_message}"
                        )

                    continue

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
            "results": results,
        }

    finally:
        db.close()
