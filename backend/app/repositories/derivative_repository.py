from app.database.models.funding_rates import FundingRate
from app.database.models.open_interest import OpenInterest


class DerivativeRepository:


    def save_funding(
        self,
        db,
        item
    ):


        db.add(

            FundingRate(

            symbol=item["symbol"],

            rate=item["rate"],

            funding_time=item["time"]

            )
        )

        db.commit()



    def save_open_interest(
        self,
        db,
        item
    ):


        db.add(

            OpenInterest(

            symbol=item["symbol"],

            value=item["value"],

            timestamp=item["time"]

            )

        )

        db.commit()