from app.database.sqlserver import SessionLocal

from app.collectors.binances.candle_collector import CandleCollector
from app.collectors.Bybit.candle_collector import CandleCollector as BybitCandleCollector

from app.repositories.market_repository import MarketRepository
from app.repositories.symbol_repository import SymbolRepository
from app.utils.freshness import normalize_timestamp_to_utc
from app.utils.network_resilience import classify_network_error
from app.utils.network_resilience import is_transient_network_error

TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"]

def run_market_job():

    print("Running Market Collector...")

    db = SessionLocal()

    try:
        symbol_repo = SymbolRepository()
        collector = CandleCollector()
        fallback_collector = BybitCandleCollector()
        repo = MarketRepository()
        symbols = symbol_repo.get_active_symbols(db)

        for symbol in symbols:
            symbol_name = symbol.symbol

            for timeframe in TIMEFRAMES:
                try:
                    last_time = repo.get_last_candle_time(db, symbol_name, timeframe)
                    candles = collector.get_candles(symbol_name, interval=timeframe)
                    if not candles:
                        candles = fallback_collector.get_candles(
                            symbol_name,
                            interval=timeframe,
                        )

                    for candle in candles:
                        if last_time:
                            last_time_utc = normalize_timestamp_to_utc(last_time)
                            last_time_ms = int(last_time_utc.timestamp() * 1000)
                            if candle["open_time_ms"] <= last_time_ms:
                                continue  # skip already saved

                        repo.save_candle(db, candle)
                except Exception as ex:
                    if not is_transient_network_error(ex):
                        print(f"Market job error {symbol_name} {timeframe}: {classify_network_error(ex)}")
                    continue
    except Exception as ex:
        db.rollback()
        if not is_transient_network_error(ex):
            print("Market job error:", classify_network_error(ex))
    finally:
        db.close()

    print("Market data saved")
