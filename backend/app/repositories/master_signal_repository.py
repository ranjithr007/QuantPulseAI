from app.database.models.master_signals import MasterSignal


class MasterSignalRepository:

    def save(self, db, data):

        db.add(MasterSignal(**data))

        db.commit()