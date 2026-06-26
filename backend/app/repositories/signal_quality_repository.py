from app.database.models.signal_quality import SignalQuality
from app.repositories._db_utils import commit_or_rollback


class SignalQualityRepository:

    def save(self, db, data):

        db.add(SignalQuality(**data))

        commit_or_rollback(db)
