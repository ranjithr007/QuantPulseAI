from app.database.models.backtest_results import BacktestResult
from app.repositories._db_utils import commit_or_rollback


class BacktestRepository:

    def save(self, db, data):

        db.add(BacktestResult(**data))

        commit_or_rollback(db)
