from app.database.models.master_signals import MasterSignal
from app.repositories._db_utils import commit_or_rollback


class MasterSignalRepository:

    def save(self, db, data):

        db.add(MasterSignal(**data))

        commit_or_rollback(db)

    def latest(self, db, symbol, timeframe=None):

        query = db.query(MasterSignal).filter(MasterSignal.symbol == symbol)

        if timeframe:
            query = query.filter(MasterSignal.timeframe == timeframe)

        return query.order_by(MasterSignal.created_at.desc()).first()
