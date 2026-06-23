from app.database.sqlserver import SessionLocal
from app.smc.smc_service import run_smc_analysis
from app.repositories.market_repository import MarketRepository
from app.repositories.symbol_repository import SymbolRepository
from app.database.models.market_candles import MarketCandle

from app.repositories.smc_repository import SMCRepository

from app.engines.smc_engine import SMCEngine

TIMEFRAMES = ["5m", "15m", "1h", "4h", "1d"]
market_repo = MarketRepository()
smc_repo = SMCRepository()

engine = SMCEngine()


def run_smc_job():

    print("Running SMC Engine...")
    db = SessionLocal()
    SYMBOLS = SymbolRepository().get_active_symbols(db)

    for item in SYMBOLS:

        symbol = item.symbol
        for tf in TIMEFRAMES:

            result = run_smc_analysis(symbol, tf)
            candles = (
                db.query(MarketCandle)
                .filter(MarketCandle.symbol == symbol)
                .order_by(MarketCandle.timeframe.desc())
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
