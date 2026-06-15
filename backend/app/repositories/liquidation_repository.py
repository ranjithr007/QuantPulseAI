from app.database.models.liquidations import Liquidation


class LiquidationRepository:

    def save(self, db, data):

        entity = Liquidation(
            symbol=data["symbol"],
            side=data["side"],
            price=data["price"],
            quantity=data["quantity"],
            value_usd=data["value_usd"],
            event_time=data["event_time"],
        )

        db.add(entity)

        db.commit()