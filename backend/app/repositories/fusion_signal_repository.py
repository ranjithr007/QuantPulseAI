from app.database.models.fusion_signal import FusionSignal


class FusionSignalRepository:

    def get_latest_tradeable_signals(self, db):

        return (
            db.query(FusionSignal)
            .filter(FusionSignal.decision != "WAIT")
            .filter(FusionSignal.confidence >= 70)
            .order_by(FusionSignal.created_at.desc())
            .limit(20)
            .all()
        )