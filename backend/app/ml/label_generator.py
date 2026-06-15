from app.database.models.ml_training_data import MLTrainingData
from app.database.models.market_data import MarketData


class LabelGenerator:

    def __init__(self, db):
        self.db = db

    def generate(self, symbol: str):

        rows = (
            self.db.query(MLTrainingData).filter(MLTrainingData.symbol == symbol).all()
        )

        updated = 0

        for row in rows:

            future = (
                self.db.query(MarketData)
                .filter(
                    MarketData.symbol == symbol, MarketData.timestamp > row.created_at
                )
                .order_by(MarketData.timestamp.asc())
                .offset(10)
                .first()
            )

            if not future:
                continue

            future_return = (
                (future.close - row.current_price) / row.current_price
            ) * 100

            row.future_price = future.close

            row.future_return = future_return

            if future_return > 0.3:

                row.label = 2

            elif future_return < -0.3:

                row.label = 0

            else:

                row.label = 1

            updated += 1

        self.db.commit()

        return {"labels_created": updated}