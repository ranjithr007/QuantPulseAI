import json
from datetime import datetime

from app.database.models.data_quality_events import DataQualityEvent
from app.repositories._db_utils import commit_or_rollback


class DataQualityEventRepository:
    def ensure_table(self, db):
        DataQualityEvent.__table__.create(bind=db.get_bind(), checkfirst=True)

    def record_events(self, db, events):
        self.ensure_table(db)

        rows = []
        for event in events or []:
            observed_at = _as_datetime(event.get("observed_at")) or datetime.utcnow()
            effective_at = _as_datetime(event.get("effective_at")) or observed_at
            row = DataQualityEvent(
                symbol=str(event.get("symbol") or "UNKNOWN")[:20],
                timeframe=str(event.get("timeframe") or "5m")[:10],
                source=str(event.get("source") or "data_quality_engine")[:40],
                category=str(event.get("category") or "GENERAL")[:40],
                severity=str(event.get("severity") or "warning")[:20],
                status=str(event.get("status") or ("BLOCKED" if event.get("blocked") else "WARN"))[:20],
                blocked=bool(event.get("blocked", False)),
                reason=str(event.get("reason") or "Data quality event")[:1000],
                details_json=json.dumps(
                    event.get("details") or {},
                    sort_keys=True,
                    default=str,
                ),
                observed_at=observed_at,
                effective_at=effective_at,
            )
            db.add(row)
            rows.append(row)

        if rows:
            commit_or_rollback(db)
            for row in rows:
                db.refresh(row)

        return [self._serialize(row) for row in rows]

    def list_events(
        self,
        db,
        symbol=None,
        timeframe=None,
        source=None,
        category=None,
        limit=100,
    ):
        self.ensure_table(db)
        query = db.query(DataQualityEvent)

        if symbol:
            query = query.filter(DataQualityEvent.symbol == symbol)

        if timeframe:
            query = query.filter(DataQualityEvent.timeframe == timeframe)
        if source:
            query = query.filter(DataQualityEvent.source == source)
        if category:
            query = query.filter(DataQualityEvent.category == category)

        rows = (
            query.order_by(DataQualityEvent.created_at.desc(), DataQualityEvent.id.desc())
            .limit(max(1, min(int(limit), 500)))
            .all()
        )
        return [self._serialize(row) for row in rows]

    def _serialize(self, row):
        return {
            "id": row.id,
            "symbol": row.symbol,
            "timeframe": row.timeframe,
            "source": row.source,
            "category": row.category,
            "severity": row.severity,
            "status": row.status,
            "blocked": bool(row.blocked),
            "reason": row.reason,
            "details": _json_value(row.details_json, {}),
            "observed_at": row.observed_at,
            "effective_at": row.effective_at,
            "created_at": row.created_at,
        }


def _json_value(value, fallback):
    try:
        return json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError):
        return fallback


def _as_datetime(value):
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo is not None else value
    if value is None:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None
