from app.database.sqlserver import SessionLocal
from app.repositories.market_repository import MarketRepository
from app.repositories.symbol_repository import SymbolRepository
from app.database.models.market_candles import MarketCandle

from app.repositories.smc_repository import SMCRepository

from app.engines.smc_engine import SMCEngine
from app.repositories._db_utils import safe_rollback
from app.utils.network_resilience import is_transient_network_error
from app.utils.network_resilience import summarize_network_error

TIMEFRAMES = ["5m", "15m", "1h", "4h", "1d"]
market_repo = MarketRepository()
smc_repo = SMCRepository()

engine = SMCEngine()


def run_smc_job():

    print("Running SMC Engine...")
    db = SessionLocal()
    try:
        SYMBOLS = SymbolRepository().get_active_symbols(db)

        for item in SYMBOLS:
            symbol = item.symbol
            for tf in TIMEFRAMES:
                try:
                    candles = (
                        db.query(MarketCandle)
                        .filter(MarketCandle.symbol == symbol)
                        .filter(MarketCandle.timeframe == tf)
                        .order_by(MarketCandle.candle_time.desc())
                        .limit(100)
                        .all()
                    )
                    if len(candles) < 20:
                        continue
                    result = engine.analyze(candles)

                    result["symbol"] = symbol

                    result["timeframe"] = tf

                    smc_repo.save(db, result)

                    # print(symbol, result["structure"], result["smc_score"])
                    # print(symbol, tf, result)
                except Exception as ex:
                    if not is_transient_network_error(ex):
                        print(f"SMC job error {symbol} {tf}: {summarize_network_error(ex)}")
                    continue
    except Exception as ex:
        safe_rollback(db)
        if not is_transient_network_error(ex):
            print("SMC job error:", summarize_network_error(ex))
    finally:
        db.close()
