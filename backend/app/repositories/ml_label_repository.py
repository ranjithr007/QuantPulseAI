from app.database.models.ml_label import MLLabel


class MLLabelRepository:

    def save(self, db, label):

        entity = MLLabel(
            symbol=label["symbol"],
            timestamp=label["timestamp"],
            current_price=label["current_price"],
            future_price=label["future_price"],
            future_return=label["future_return"],
            label=label["label"],
        )

        db.add(entity)

        db.commit()

        return entity