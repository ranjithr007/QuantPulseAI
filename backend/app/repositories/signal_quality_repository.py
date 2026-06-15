from app.database.models.signal_quality import SignalQuality


class SignalQualityRepository:

    def save(self, db, data):

        db.add(SignalQuality(**data))

        db.commit()