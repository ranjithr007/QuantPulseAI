from app.database.models.ai_signals import AISignal
from app.repositories._db_utils import commit_or_rollback


class AISignalRepository:

    def save(self, db, data):

        db.add(AISignal(**data))

        commit_or_rollback(db)

    def latest(self, db, symbol, timeframe=None):

        query = db.query(AISignal).filter(AISignal.symbol == symbol)

        if timeframe:
            query = query.filter(AISignal.timeframe == timeframe)

        return query.order_by(AISignal.created_at.desc()).first()
