import json
from datetime import datetime

from app.database.models.point_in_time_snapshots import DecisionSnapshot
from app.repositories.point_in_time_snapshot_repository import save_decision_snapshot


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
        return {
            symbol: self.latest(db, symbol)
            for symbol in sorted({str(item).upper() for item in symbols or []})
        }

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
