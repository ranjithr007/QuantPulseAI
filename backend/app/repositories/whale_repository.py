from app.database.models.whale_trades import WhaleTrade
from app.repositories._db_utils import commit_or_rollback


class WhaleRepository:

    def save(self, db, trade):

        db.add(WhaleTrade(**trade))

        commit_or_rollback(db)
