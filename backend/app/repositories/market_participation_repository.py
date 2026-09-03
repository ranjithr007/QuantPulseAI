import json
from datetime import datetime
from datetime import timezone

from sqlalchemy import func

from app.database.models.point_in_time_snapshots import DecisionSnapshot
from app.repositories.point_in_time_snapshot_repository import save_decision_snapshot
from app.utils.freshness import normalize_timestamp_to_utc


MARKET_PARTICIPATION_DECISION_VERSION = "market_participation_trend_v1"
MARKET_PARTICIPATION_FEATURE_VERSION = "spot_participation_features_v1"
MARKET_PARTICIPATION_TIMEFRAME = "stack"


class MarketParticipationRepository:
    @staticmethod
    def ensure_table(db):
        DecisionSnapshot.__table__.create(bind=db.get_bind(), checkfirst=True)

    def save(self, db, payload, *, data_generation_id=None):
        self.ensure_table(db)
        source_timestamp = _source_timestamp(payload) or datetime.utcnow()
        snapshot = {
            **payload,
            "timeframe": MARKET_PARTICIPATION_TIMEFRAME,
            "source_timestamp": source_timestamp,
            "effective_timestamp": source_timestamp,
            "feature_version": MARKET_PARTICIPATION_FEATURE_VERSION,
            "decision_version": MARKET_PARTICIPATION_DECISION_VERSION,
            "quality_state": payload.get("quality_state") or "DEGRADED",
            "decision": payload.get("direction") or "NEUTRAL",
            "confidence": payload.get("confidence") or 0,
            "regime": payload.get("direction") or "NEUTRAL",
            "data_generation_id": data_generation_id,
        }
        return save_decision_snapshot(db, snapshot)

    def latest(self, db, symbol):
        self.ensure_table(db)
        row = (
            db.query(DecisionSnapshot)
            .filter(
                DecisionSnapshot.symbol == str(symbol).upper(),
                DecisionSnapshot.timeframe == MARKET_PARTICIPATION_TIMEFRAME,
                DecisionSnapshot.decision_version
                == MARKET_PARTICIPATION_DECISION_VERSION,
            )
            .order_by(
                DecisionSnapshot.effective_timestamp.desc(),
                DecisionSnapshot.id.desc(),
            )
            .first()
        )
        return self.serialize(row)

    def latest_for_symbols(self, db, symbols):
        normalized = sorted({str(item).upper() for item in symbols or []})
        if not normalized:
            return {}

        self.ensure_table(db)
        ranked = (
            db.query(
                DecisionSnapshot.id.label("decision_snapshot_id"),
                func.row_number()
                .over(
                    partition_by=DecisionSnapshot.symbol,
                    order_by=(
                        DecisionSnapshot.effective_timestamp.desc(),
                        DecisionSnapshot.id.desc(),
                    ),
                )
                .label("row_number"),
            )
            .filter(
                DecisionSnapshot.symbol.in_(normalized),
                DecisionSnapshot.timeframe == MARKET_PARTICIPATION_TIMEFRAME,
                DecisionSnapshot.decision_version
                == MARKET_PARTICIPATION_DECISION_VERSION,
            )
            .subquery()
        )
        rows = (
            db.query(DecisionSnapshot)
            .join(
                ranked,
                DecisionSnapshot.id == ranked.c.decision_snapshot_id,
            )
            .filter(ranked.c.row_number == 1)
            .all()
        )
        return {row.symbol: self.serialize(row) for row in rows}

    def history_through(self, db, symbol, as_of_timestamp=None, *, limit=5000):
        self.ensure_table(db)
        query = db.query(DecisionSnapshot).filter(
            DecisionSnapshot.symbol == str(symbol).upper(),
            DecisionSnapshot.timeframe == MARKET_PARTICIPATION_TIMEFRAME,
            DecisionSnapshot.decision_version
            == MARKET_PARTICIPATION_DECISION_VERSION,
        )
        if as_of_timestamp is not None:
            cutoff = normalize_timestamp_to_utc(as_of_timestamp)
            if cutoff.tzinfo is not None:
                cutoff = cutoff.astimezone(timezone.utc).replace(tzinfo=None)
            query = query.filter(DecisionSnapshot.effective_timestamp <= cutoff)
        rows = (
            query.order_by(
                DecisionSnapshot.effective_timestamp.desc(),
                DecisionSnapshot.id.desc(),
            )
            .limit(max(0, int(limit)))
            .all()
        )
        return [self.serialize(row) for row in reversed(rows)]

    @staticmethod
    def serialize(row):
        if row is None:
            return None
        try:
            payload = json.loads(row.snapshot_json or "{}")
        except (TypeError, ValueError):
            payload = {}
        return {
            **payload,
            "id": row.id,
            "symbol": row.symbol,
            "direction": row.decision,
            "confidence": row.confidence,
            "quality_state": row.quality_state,
            "effective_timestamp": row.effective_timestamp,
            "created_at": row.created_at,
            "decision_version": row.decision_version,
        }


def _source_timestamp(payload):
    timestamps = []
    for item in ((payload.get("spot") or {}).get("timeframes") or []):
        value = item.get("source_timestamp")
        if isinstance(value, datetime):
            timestamps.append(value.replace(tzinfo=None))
    return max(timestamps) if timestamps else None
