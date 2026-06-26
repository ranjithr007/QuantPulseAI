from app.database.models.fusion_signal import FusionSignal


class FusionSignalRepository:

    def get_latest_tradeable_signals(self, db, timeframe=None):

        query = (
            db.query(FusionSignal)
            .filter(FusionSignal.decision != "WAIT")
            .filter(FusionSignal.confidence >= 70)
        )

        if timeframe:
            query = query.filter(FusionSignal.timeframe == timeframe)

        return query.order_by(FusionSignal.created_at.desc()).limit(20).all()
