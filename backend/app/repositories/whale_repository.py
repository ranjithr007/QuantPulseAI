from app.database.models.whale_trades import WhaleTrade


class WhaleRepository:

    def save(self, db, trade):

        db.add(WhaleTrade(**trade))

        db.commit()