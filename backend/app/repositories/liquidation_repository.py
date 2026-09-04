from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError

from app.database.models.liquidations import Liquidation
from app.repositories._db_utils import commit_or_rollback, safe_rollback


class LiquidationRepository:

    def save(self, db, data):
        entity, _ = self.save_if_new(db, data)
        return entity

    def save_if_new(self, db, data):
        venue = str(data.get("venue") or "BINANCE").upper()
        symbol = str(data["symbol"]).upper()
        exchange_event_id = data.get("exchange_event_id")
        normalized_event_id = (
            str(exchange_event_id) if exchange_event_id is not None else None
        )
        values = dict(
            venue=venue,
            exchange_event_id=normalized_event_id,
            symbol=symbol,
            side=data["side"],
            price=data["price"],
            quantity=data["quantity"],
            value_usd=data["value_usd"],
            event_time=data["event_time"],
        )

        # Events without an exchange identifier cannot be safely deduplicated.
        if normalized_event_id is None:
            entity = Liquidation(**values)
            db.add(entity)
            commit_or_rollback(db)
            return entity, True

        dialect = str(db.get_bind().dialect.name).lower()
        if dialect in {"postgresql", "sqlite"}:
            insert_factory = (
                postgresql_insert if dialect == "postgresql" else sqlite_insert
            )
            statement = insert_factory(Liquidation).values(**values)
            statement = statement.on_conflict_do_nothing(
                index_elements=["venue", "symbol", "exchange_event_id"]
            )
            result = db.execute(statement)
            created = result.rowcount == 1
            commit_or_rollback(db)
            entity = self._find_existing(
                db,
                venue=venue,
                symbol=symbol,
                exchange_event_id=normalized_event_id,
            )
            if entity is None:
                raise RuntimeError("Liquidation upsert completed without a stored row")
            return entity, created

        # Compatibility fallback for any non-PostgreSQL test or legacy backend.
        # The IntegrityError branch resolves the remaining insert race safely.
        entity = Liquidation(**values)
        db.add(entity)
        try:
            commit_or_rollback(db)
            return entity, True
        except IntegrityError:
            safe_rollback(db)
            existing = self._find_existing(
                db,
                venue=venue,
                symbol=symbol,
                exchange_event_id=normalized_event_id,
            )
            if existing is None:
                raise
            return existing, False

    @staticmethod
    def _find_existing(db, *, venue, symbol, exchange_event_id):
        return (
            db.query(Liquidation)
            .filter(
                Liquidation.venue == venue,
                Liquidation.symbol == symbol,
                Liquidation.exchange_event_id == exchange_event_id,
            )
            .first()
        )
