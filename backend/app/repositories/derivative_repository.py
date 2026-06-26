from app.database.models.funding_rates import FundingRate
from app.database.models.open_interest import OpenInterest
from app.repositories._db_utils import commit_or_rollback


class DerivativeRepository:
    def save_funding(self, db, item):
        db.add(
            FundingRate(
                symbol=item["symbol"],
                rate=item["rate"],
                funding_time=item["time"],
            )
        )
        commit_or_rollback(db)

    def save_open_interest(self, db, item):
        db.add(
            OpenInterest(
                symbol=item["symbol"],
                value=item["value"],
                timestamp=item["time"],
            )
        )
        commit_or_rollback(db)
