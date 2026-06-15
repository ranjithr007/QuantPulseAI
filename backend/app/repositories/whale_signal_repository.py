from app.database.models.whale_signals import WhaleSignal


class WhaleSignalRepository:

    def save(self, db, data):

        db.add(WhaleSignal(**data))

        db.commit()