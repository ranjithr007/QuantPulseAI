from app.database.sqlserver import SessionLocal

from app.collectors.binances.candle_collector import CandleCollector
from app.collectors.Bybit.candle_collector import (
    CandleCollector as BybitCandleCollector,
)

from app.repositories.market_repository import MarketRepository
from app.repositories.symbol_repository import SymbolRepository
from app.utils.freshness import normalize_timestamp_to_utc
from app.utils.network_resilience import classify_network_error
from app.utils.network_resilience import is_transient_network_error

TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"]


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
                    last_time = repo.get_last_candle_time(
                        db,
                        symbol_name,
                        timeframe,
                    )

                    candles = collector.get_candles(
                        symbol_name,
                        interval=timeframe,
                    )

                    if not candles:
                        source = "BYBIT"

                        candles = fallback_collector.get_candles(
                            symbol_name,
                            interval=timeframe,
                        )

                    candles = candles or []

                    fetched_count = len(candles)
                    total_fetched += fetched_count

                    last_time_ms = None

                    if last_time:
                        last_time_utc = normalize_timestamp_to_utc(last_time)
                        last_time_ms = int(last_time_utc.timestamp() * 1000)

                    for candle in candles:
                        candle_open_time_ms = candle.get("open_time_ms")

                        if (
                            last_time_ms is not None
                            and candle_open_time_ms is not None
                            and candle_open_time_ms <= last_time_ms
                        ):
                            skipped_count += 1
                            total_skipped += 1
                            continue

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
            "active_symbols": len(symbols),
            "timeframes": len(TIMEFRAMES),
            "processed_combinations": len(results),
            "total_fetched": total_fetched,
            "total_saved": total_saved,
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
            "total_skipped": total_skipped,
            "total_failed": total_failed + 1,
            "results": results,
        }

    finally:
        db.close()
