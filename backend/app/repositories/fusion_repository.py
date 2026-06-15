from app.database.models.fusion_signal import FusionSignal


class FusionSignalRepository:

    def save(self, db, data):

        record = FusionSignal(
            symbol=data["symbol"],
            decision=data["decision"],
            confidence=data["confidence"],
            ml_score=data.get("ml_score", 0),
            regime_score=data.get("regime_score", 0),
            orderflow_score=data.get("orderflow_score", 0),
            smc_score=data.get("smc_score", 0),
            liquidation_score=data.get("liquidation_score", 0),
            whale_score=data.get("whale_score", 0),
        )

        db.add(record)

        db.commit()

        db.refresh(record)

        return record

    def get_latest_signals(self, db, limit=20):

        try:
            return (
                db.query(FusionSignal)
                .order_by(FusionSignal.created_at.desc())
                .limit(limit)
                .all()
            )

        finally:
            db.close()