from app.database.sqlserver import SessionLocal

from app.database.models.master_signals import MasterSignal

from app.engines.backtest_engine import BacktestEngine

from app.repositories.backtest_repository import BacktestRepository


def run_backtest_job():

    print("Running Backtest Engine")

    db = SessionLocal()

    signals = (
        db.query(MasterSignal).filter(MasterSignal.signal != "WAIT").limit(50).all()
    )

    for signal in signals:

        result = BacktestEngine().test(db, signal)

        if result:

            # print(result)

            BacktestRepository().save(db, result)

    db.close()