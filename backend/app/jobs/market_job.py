from app.database.sqlserver import SessionLocal

from app.collectors.binances.candle_collector import CandleCollector

from app.repositories.market_repository import MarketRepository
from app.repositories.symbol_repository import SymbolRepository
from app.utils.freshness import normalize_timestamp_to_utc

TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"]

def run_market_job():

    print("Running Market Collector...")

    db = SessionLocal()
    symbol_repo = SymbolRepository()

    symbols = symbol_repo.get_active_symbols(db)

    collector = CandleCollector()

    repo = MarketRepository()

    for symbol in symbols:

        symbol_name = symbol.symbol

        for timeframe in TIMEFRAMES:
            # print("Collecting:", symbol_name)
            last_time = repo.get_last_candle_time(db, symbol_name, timeframe)
            candles = collector.get_candles(symbol_name, interval=timeframe)

            for candle in candles:
                # print(candle)
                if last_time:
                    last_time_utc = normalize_timestamp_to_utc(last_time)
                    last_time_ms = int(last_time_utc.timestamp() * 1000)
                    if candle["open_time_ms"] <= last_time_ms:
                        continue;  # skip already saved
                
                repo.save_candle(db, candle)
            

    db.close()

    print("Market data saved")
