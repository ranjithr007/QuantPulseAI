from app.database.sqlserver import SessionLocal

from app.database.models.master_signals import MasterSignal

from app.engines.signal_quality_engine import SignalQualityEngine

from app.repositories.signal_quality_repository import SignalQualityRepository


def run_signal_quality_job():

    print("Running Signal Quality Engine")

    db = SessionLocal()

    signals = (
        db.query(MasterSignal).order_by(MasterSignal.created_at.desc()).limit(20).all()
    )

    for signal in signals:

        result = SignalQualityEngine().analyze(signal)

        # print(result)

        SignalQualityRepository().save(db, result)

    db.close()