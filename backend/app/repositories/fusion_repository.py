from app.database.models.fusion_signal import FusionSignal
from app.repositories._db_utils import commit_or_rollback


class FusionSignalRepository:

    def save(self, db, data):

        record = FusionSignal(
            symbol=data["symbol"],
            timeframe=data.get("timeframe"),
            decision=data["decision"],
            confidence=data["confidence"],
            ml_score=data.get("ml_score", 0),
            regime_score=data.get("regime_score", 0),
            orderflow_score=data.get("orderflow_score", 0),
            smc_score=data.get("smc_score", 0),
            liquidation_score=data.get("liquidation_score", 0),
            whale_score=data.get("whale_score", 0),
            data_generation_id=data.get("data_generation_id"),
        )

        db.add(record)

        commit_or_rollback(db)

        db.refresh(record)

        return record

    def get_latest_signals(self, db, limit=20):

        return (
            db.query(FusionSignal)
            .order_by(FusionSignal.created_at.desc())
            .limit(limit)
            .all()
        )
