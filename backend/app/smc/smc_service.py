from app.database.sqlserver import SessionLocal

from app.repositories.candle_repository import get_latest_candles

from app.repositories.smc_repository import SMCRepository

from app.smc.smc_engine import analyze_smc


def run_smc_analysis(symbol, timeframe):

    db = SessionLocal()

    try:

        candles = get_latest_candles(db, symbol, timeframe)

        if len(candles) < 20:

            return None

        result = analyze_smc(candles)

        SMCRepository.save_smc_signal(db, symbol, timeframe, result)

        return result

    except Exception:
        db.rollback()
        raise

    finally:

        db.close()
