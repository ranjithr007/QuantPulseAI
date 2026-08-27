import json
from datetime import datetime

from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app.database.models.app_notification import AppNotification
from app.database.sqlserver import USING_SQLITE_FALLBACK
from app.repositories._db_utils import commit_or_rollback


VALID_SEVERITIES = {"INFO", "SUCCESS", "WARNING", "CRITICAL"}


class NotificationRepository:
    """Database-backed notification outbox for the authenticated application UI."""

    def ensure_table(self, db):
        engine = db.get_bind()
        if not USING_SQLITE_FALLBACK and engine.dialect.name != "sqlite":
            return
        connection = db.connection()
        AppNotification.__table__.create(bind=connection, checkfirst=True)
        if AppNotification.__tablename__ not in inspect(connection).get_table_names():
            raise RuntimeError("Application notification ledger could not be initialized")

    def create(
        self,
        db,
        *,
        event_key,
        category,
        event_type,
        severity,
        title,
        message,
        symbol=None,
        paper_trade_id=None,
        metadata=None,
        created_at=None,
        commit=False,
    ):
        """Insert once by event key and return ``(row, created)``.

        The savepoint keeps a rare concurrent duplicate from rolling back the
        surrounding paper-trade transaction.
        """

        self.ensure_table(db)
        normalized_key = str(event_key).strip()[:180]
        existing = (
            db.query(AppNotification)
            .filter(AppNotification.event_key == normalized_key)
            .first()
        )
        if existing is not None:
            return existing, False

        row = AppNotification(
            event_key=normalized_key,
            category=str(category or "SYSTEM").upper()[:30],
            event_type=str(event_type or "GENERAL").upper()[:50],
            severity=(
                str(severity or "INFO").upper()
                if str(severity or "INFO").upper() in VALID_SEVERITIES
                else "INFO"
            ),
            title=str(title or "QuantPulseAI update")[:160],
            message=str(message or ""),
            symbol=str(symbol).upper()[:30] if symbol else None,
            paper_trade_id=paper_trade_id,
            metadata_json=(
                json.dumps(metadata, sort_keys=True, default=str)
                if metadata is not None
                else None
            ),
            created_at=created_at or datetime.utcnow(),
        )
        try:
            with db.begin_nested():
                db.add(row)
                db.flush()
        except IntegrityError:
            existing = (
                db.query(AppNotification)
                .filter(AppNotification.event_key == normalized_key)
                .first()
            )
            if existing is None:
                raise
            return existing, False

        if commit:
            commit_or_rollback(db)
            db.refresh(row)
        return row, True

    def list(self, db, *, unread_only=False, limit=50):
        self.ensure_table(db)
        query = db.query(AppNotification)
        if unread_only:
            query = query.filter(AppNotification.read_at.is_(None))
        return (
            query.order_by(
                AppNotification.created_at.desc(),
                AppNotification.id.desc(),
            )
            .limit(max(1, min(int(limit), 200)))
            .all()
        )

    def unread_count(self, db):
        self.ensure_table(db)
        return (
            db.query(AppNotification)
            .filter(AppNotification.read_at.is_(None))
            .count()
        )

    def mark_read(self, db, notification_id):
        self.ensure_table(db)
        row = db.query(AppNotification).filter(AppNotification.id == notification_id).first()
        if row is None:
            return None
        if row.read_at is None:
            row.read_at = datetime.utcnow()
            commit_or_rollback(db)
            db.refresh(row)
        return row

    def mark_all_read(self, db):
        self.ensure_table(db)
        read_at = datetime.utcnow()
        count = (
            db.query(AppNotification)
            .filter(AppNotification.read_at.is_(None))
            .update({AppNotification.read_at: read_at}, synchronize_session=False)
        )
        commit_or_rollback(db)
        return count, read_at


def notification_payload(row):
    return {
        "id": row.id,
        "eventKey": row.event_key,
        "category": row.category,
        "eventType": row.event_type,
        "severity": row.severity,
        "title": row.title,
        "message": row.message,
        "symbol": row.symbol,
        "paperTradeId": row.paper_trade_id,
        "metadata": _json_value(row.metadata_json, {}),
        "createdAt": row.created_at,
        "readAt": row.read_at,
        "isRead": row.read_at is not None,
    }


def _json_value(value, fallback):
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback
