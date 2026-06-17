from app.database.models.master_signals import MasterSignal


class MasterSignalRepository:

    def save(self, db, data):

        db.add(MasterSignal(**data))

        db.commit()

    def latest(self, db, symbol):

        return (
            db.query(MasterSignal)
            .filter(MasterSignal.symbol == symbol)
            .order_by(MasterSignal.created_at.desc())
            .first()
        )
