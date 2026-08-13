from app.database.models.fusion_signal import FusionSignal
from app.governance.evidence_policy import MIN_ENTRY_CONFIDENCE


class FusionSignalRepository:

    def get_latest_tradeable_signals(self, db, timeframe=None):

        query = (
            db.query(FusionSignal)
            .filter(FusionSignal.decision != "WAIT")
            .filter(FusionSignal.confidence >= MIN_ENTRY_CONFIDENCE)
        )

        if timeframe:
            query = query.filter(FusionSignal.timeframe == timeframe)

        return query.order_by(FusionSignal.created_at.desc()).limit(20).all()
