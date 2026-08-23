from app.database.models.liquidations import Liquidation
from app.repositories._db_utils import commit_or_rollback


class LiquidationRepository:

    def save(self, db, data):
        venue = str(data.get("venue") or "BINANCE").upper()
        exchange_event_id = data.get("exchange_event_id")
        if exchange_event_id is not None:
            existing = (
                db.query(Liquidation)
                .filter(
                    Liquidation.venue == venue,
                    Liquidation.symbol == str(data["symbol"]).upper(),
                    Liquidation.exchange_event_id == str(exchange_event_id),
                )
                .first()
            )
            if existing is not None:
                return existing

        entity = Liquidation(
            venue=venue,
            exchange_event_id=(
                str(exchange_event_id) if exchange_event_id is not None else None
            ),
            symbol=data["symbol"],
            side=data["side"],
            price=data["price"],
            quantity=data["quantity"],
            value_usd=data["value_usd"],
            event_time=data["event_time"],
        )

        db.add(entity)

        commit_or_rollback(db)
        return entity
