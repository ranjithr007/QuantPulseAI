import json
from datetime import datetime
from datetime import timezone

from sqlalchemy.exc import IntegrityError

from app.database.models.point_in_time_snapshots import DecisionSnapshot
from app.database.models.point_in_time_snapshots import FeatureSnapshot
from app.repositories._db_utils import commit_or_rollback
from app.utils.freshness import normalize_timestamp_to_utc


def _to_naive_utc(timestamp):
    if timestamp is None:
        return None

    normalized = normalize_timestamp_to_utc(timestamp)
    if normalized is None:
        return None
    if normalized.tzinfo is not None:
        return normalized.astimezone(timezone.utc).replace(tzinfo=None)
    return normalized


def _snapshot_json(snapshot):
    return json.dumps(snapshot, default=str, sort_keys=True)


def _ensure_snapshot_tables(db):
    bind = db.get_bind()
    FeatureSnapshot.__table__.create(bind=bind, checkfirst=True)
    DecisionSnapshot.__table__.create(bind=bind, checkfirst=True)


def save_feature_snapshot(db, snapshot):
    _ensure_snapshot_tables(db)
    existing = _get_existing_feature_snapshot(db, snapshot)
    if existing is not None:
        return existing

    record = FeatureSnapshot(
        symbol=snapshot["symbol"],
        timeframe=snapshot["timeframe"],
        source_timestamp=_to_naive_utc(snapshot["source_timestamp"]),
        effective_timestamp=_to_naive_utc(snapshot["effective_timestamp"]),
        feature_version=snapshot["feature_version"],
        quality_state=snapshot["quality_state"],
        snapshot_json=_snapshot_json(snapshot),
        created_at=datetime.utcnow(),
    )

    db.add(record)
    try:
        commit_or_rollback(db)
    except IntegrityError:
        existing = _get_existing_feature_snapshot(db, snapshot)
        if existing is not None:
            return existing
        raise
    db.refresh(record)
    return record


def save_decision_snapshot(db, snapshot):
    _ensure_snapshot_tables(db)
    existing = _get_existing_decision_snapshot(db, snapshot)
    if existing is not None:
        return existing

    record = DecisionSnapshot(
        symbol=snapshot["symbol"],
        timeframe=snapshot["timeframe"],
        source_timestamp=_to_naive_utc(snapshot["source_timestamp"]),
        effective_timestamp=_to_naive_utc(snapshot["effective_timestamp"]),
        feature_version=snapshot["feature_version"],
        decision_version=snapshot["decision_version"],
        quality_state=snapshot["quality_state"],
        decision=snapshot["decision"],
        confidence=snapshot.get("confidence"),
        regime=snapshot.get("regime"),
        thesis_id=snapshot.get("thesis_id"),
        snapshot_json=_snapshot_json(snapshot),
        created_at=datetime.utcnow(),
    )

    db.add(record)
    try:
        commit_or_rollback(db)
    except IntegrityError:
        existing = _get_existing_decision_snapshot(db, snapshot)
        if existing is not None:
            return existing
        raise
    db.refresh(record)
    return record


def get_feature_snapshot_as_of(db, symbol, timeframe, as_of_timestamp, feature_version=None):
    _ensure_snapshot_tables(db)
    query = (
        db.query(FeatureSnapshot)
        .filter(FeatureSnapshot.symbol == symbol)
        .filter(FeatureSnapshot.timeframe == timeframe)
        .filter(FeatureSnapshot.effective_timestamp <= _to_naive_utc(as_of_timestamp))
    )

    if feature_version:
        query = query.filter(FeatureSnapshot.feature_version == feature_version)

    return query.order_by(
        FeatureSnapshot.effective_timestamp.desc(),
        FeatureSnapshot.id.desc(),
    ).first()


def get_decision_snapshot_as_of(db, symbol, timeframe, as_of_timestamp, decision_version=None):
    _ensure_snapshot_tables(db)
    query = (
        db.query(DecisionSnapshot)
        .filter(DecisionSnapshot.symbol == symbol)
        .filter(DecisionSnapshot.timeframe == timeframe)
        .filter(DecisionSnapshot.effective_timestamp <= _to_naive_utc(as_of_timestamp))
    )

    if decision_version:
        query = query.filter(DecisionSnapshot.decision_version == decision_version)

    return query.order_by(
        DecisionSnapshot.effective_timestamp.desc(),
        DecisionSnapshot.id.desc(),
    ).first()


def _get_existing_feature_snapshot(db, snapshot):
    return (
        db.query(FeatureSnapshot)
        .filter(FeatureSnapshot.symbol == snapshot["symbol"])
        .filter(FeatureSnapshot.timeframe == snapshot["timeframe"])
        .filter(FeatureSnapshot.effective_timestamp == _to_naive_utc(snapshot["effective_timestamp"]))
        .filter(FeatureSnapshot.feature_version == snapshot["feature_version"])
        .first()
    )


def _get_existing_decision_snapshot(db, snapshot):
    return (
        db.query(DecisionSnapshot)
        .filter(DecisionSnapshot.symbol == snapshot["symbol"])
        .filter(DecisionSnapshot.timeframe == snapshot["timeframe"])
        .filter(DecisionSnapshot.effective_timestamp == _to_naive_utc(snapshot["effective_timestamp"]))
        .filter(DecisionSnapshot.decision_version == snapshot["decision_version"])
        .first()
    )
