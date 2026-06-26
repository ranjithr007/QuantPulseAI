from app.database.models.whale_signals import WhaleSignal
from app.repositories._db_utils import commit_or_rollback


class WhaleSignalRepository:

    def save(self, db, data):

        db.add(WhaleSignal(**data))

        commit_or_rollback(db)
