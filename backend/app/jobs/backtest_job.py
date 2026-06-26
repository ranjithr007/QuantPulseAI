from app.database.sqlserver import SessionLocal

from app.database.models.master_signals import MasterSignal

from app.engines.backtest_engine import BacktestEngine

from app.repositories.backtest_repository import BacktestRepository
from app.utils.network_resilience import is_transient_network_error
from app.utils.network_resilience import summarize_network_error


def run_backtest_job():

    print("Running Backtest Engine")

    db = SessionLocal()

    try:
        signals = (
            db.query(MasterSignal).filter(MasterSignal.signal != "WAIT").limit(50).all()
        )

        for signal in signals:
            try:
                result = BacktestEngine().test(db, signal)

                if result:

                    BacktestRepository().save(db, result)
            except Exception as ex:
                if not is_transient_network_error(ex):
                    print(f"Backtest job error {signal.symbol}: {summarize_network_error(ex)}")
                continue
    except Exception as ex:
        db.rollback()
        if not is_transient_network_error(ex):
            print("Backtest job error:", summarize_network_error(ex))
    finally:
        db.close()
