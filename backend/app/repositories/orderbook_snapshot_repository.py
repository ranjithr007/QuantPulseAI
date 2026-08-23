from app.database.models.orderbook_snapshots import OrderBookSnapshot
from app.repositories._db_utils import commit_or_rollback
from app.utils.freshness import normalize_timestamp_to_utc


class OrderBookSnapshotRepository:
    def save(self, db, payload):
        existing = (
            db.query(OrderBookSnapshot)
            .filter(
                OrderBookSnapshot.venue == payload["venue"],
                OrderBookSnapshot.symbol == payload["symbol"],
                OrderBookSnapshot.last_update_id == payload["last_update_id"],
            )
            .first()
        )
        if existing is not None:
            return existing
        record = OrderBookSnapshot(**payload)
        db.add(record)
        commit_or_rollback(db)
        return record

    def history_through(self, db, symbol, as_of_timestamp=None, *, limit=5000):
        query = db.query(OrderBookSnapshot).filter(
            OrderBookSnapshot.symbol == str(symbol).upper()
        )
        if as_of_timestamp is not None:
            cutoff = normalize_timestamp_to_utc(as_of_timestamp)
            if cutoff.tzinfo is not None:
                cutoff = cutoff.replace(tzinfo=None)
            query = query.filter(OrderBookSnapshot.event_time <= cutoff)
        return list(
            reversed(
                query.order_by(
                    OrderBookSnapshot.event_time.desc(),
                    OrderBookSnapshot.id.desc(),
                )
                .limit(max(0, int(limit)))
                .all()
            )
        )
