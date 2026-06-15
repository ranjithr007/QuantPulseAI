from app.database.models.backtest_results import BacktestResult


class BacktestRepository:

    def save(self, db, data):

        db.add(BacktestResult(**data))

        db.commit()