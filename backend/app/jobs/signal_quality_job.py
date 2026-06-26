from app.database.sqlserver import SessionLocal

from app.database.models.master_signals import MasterSignal

from app.engines.signal_quality_engine import SignalQualityEngine

from app.repositories.signal_quality_repository import SignalQualityRepository
from app.repositories._db_utils import safe_rollback
from app.utils.network_resilience import is_transient_network_error
from app.utils.network_resilience import summarize_network_error


def run_signal_quality_job():

    print("Running Signal Quality Engine")

    db = SessionLocal()
    try:
        signals = (
            db.query(MasterSignal).order_by(MasterSignal.created_at.desc()).limit(20).all()
        )

        for signal in signals:
            try:
                result = SignalQualityEngine().analyze(signal)

                # print(result)

                SignalQualityRepository().save(db, result)
            except Exception as ex:
                if not is_transient_network_error(ex):
                    print(
                        f"Signal quality job error {getattr(signal, 'symbol', 'UNKNOWN')}: {summarize_network_error(ex)}"
                    )
                continue
    except Exception as ex:
        safe_rollback(db)
        if not is_transient_network_error(ex):
            print("Signal quality job error:", summarize_network_error(ex))
    finally:
        db.close()
