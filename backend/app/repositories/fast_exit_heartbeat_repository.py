import json
from datetime import timezone

from sqlalchemy import insert, select, update

from app.database.operational_tables import fast_exit_heartbeats


class FastExitHeartbeatRepository:
    SINGLETON_ID = 1

    def save(self, db, state):
        price_stream = state.get("last_price_stream")
        values = {
            "last_attempt_at": _naive_utc(state.get("last_attempt_at")),
            "last_success_at": _naive_utc(state.get("last_success_at")),
            "last_status": str(state.get("last_status") or "FAILED")[:20],
            "last_duration_seconds": state.get("last_duration_seconds"),
            "last_error": state.get("last_error"),
            "consecutive_failures": int(state.get("consecutive_failures") or 0),
            "price_stream_json": (
                json.dumps(price_stream, separators=(",", ":"), sort_keys=True)
                if isinstance(price_stream, dict)
                else None
            ),
        }
        result = db.execute(
            update(fast_exit_heartbeats)
            .where(fast_exit_heartbeats.c.id == self.SINGLETON_ID)
            .values(**values)
        )
        if result.rowcount == 0:
            db.execute(
                insert(fast_exit_heartbeats).values(id=self.SINGLETON_ID, **values)
            )
        db.commit()
        return values

    def load(self, db):
        row = db.execute(
            select(fast_exit_heartbeats).where(
                fast_exit_heartbeats.c.id == self.SINGLETON_ID
            )
        ).mappings().first()
        if row is None:
            return None
        try:
            price_stream = json.loads(row["price_stream_json"]) if row["price_stream_json"] else None
        except (TypeError, ValueError):
            price_stream = None
        return {
            "last_attempt_at": row["last_attempt_at"],
            "last_success_at": row["last_success_at"],
            "last_status": row["last_status"],
            "last_duration_seconds": row["last_duration_seconds"],
            "last_error": row["last_error"],
            "consecutive_failures": row["consecutive_failures"],
            "last_price_stream": price_stream,
        }


def _naive_utc(value):
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)
