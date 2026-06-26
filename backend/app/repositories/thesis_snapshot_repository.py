import json
from datetime import datetime
from datetime import timezone

from app.database.models.thesis_snapshots import ThesisSnapshot
from app.repositories._db_utils import flush_or_rollback
from app.utils.freshness import normalize_timestamp_to_utc


THESIS_SNAPSHOT_VERSION = "thesis_snapshot_v1"


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


def ensure_thesis_snapshot_table(db):
    ThesisSnapshot.__table__.create(bind=db.get_bind(), checkfirst=True)


def save_thesis_snapshot(db, thesis, *, source_timestamp=None, effective_timestamp=None):
    ensure_thesis_snapshot_table(db)
    effective_ts = _to_naive_utc(effective_timestamp or getattr(thesis, "updated_at", None) or datetime.utcnow())
    existing = (
        db.query(ThesisSnapshot)
        .filter(ThesisSnapshot.thesis_id == thesis.id)
        .filter(ThesisSnapshot.effective_timestamp == effective_ts)
        .filter(ThesisSnapshot.snapshot_version == THESIS_SNAPSHOT_VERSION)
        .first()
    )
    if existing is not None:
        return existing

    snapshot = {
        "thesis_id": thesis.id,
        "thesis_key": thesis.thesis_key,
        "symbol": thesis.symbol,
        "side": thesis.side,
        "title": thesis.title,
        "lifecycle_state": thesis.lifecycle_state,
        "lifecycle_reason": getattr(thesis, "lifecycle_reason", None),
        "source_signal": getattr(thesis, "source_signal", None),
        "confidence": getattr(thesis, "confidence", None),
        "mode": getattr(thesis, "mode", None),
        "entry_timeframe": getattr(thesis, "entry_timeframe", None),
        "timeframe_stack": getattr(thesis, "timeframe_stack", None),
        "regime": getattr(thesis, "regime", None),
        "trade_plan_id": getattr(thesis, "trade_plan_id", None),
        "risk_decision_id": getattr(thesis, "risk_decision_id", None),
        "paper_trade_id": getattr(thesis, "paper_trade_id", None),
        "assumptions_json": getattr(thesis, "assumptions_json", None),
        "invalidation_json": getattr(thesis, "invalidation_json", None),
        "targets_json": getattr(thesis, "targets_json", None),
        "scenario_json": getattr(thesis, "scenario_json", None),
        "contradiction_json": getattr(thesis, "contradiction_json", None),
        "created_at": getattr(thesis, "created_at", None),
        "updated_at": getattr(thesis, "updated_at", None),
        "invalidated_at": getattr(thesis, "invalidated_at", None),
        "resolved_at": getattr(thesis, "resolved_at", None),
    }
    record = ThesisSnapshot(
        thesis_id=thesis.id,
        thesis_key=thesis.thesis_key,
        symbol=thesis.symbol,
        side=thesis.side,
        lifecycle_state=thesis.lifecycle_state,
        source_timestamp=_to_naive_utc(source_timestamp or effective_ts),
        effective_timestamp=effective_ts,
        snapshot_version=THESIS_SNAPSHOT_VERSION,
        snapshot_json=_snapshot_json(snapshot),
        created_at=datetime.utcnow(),
    )
    db.add(record)
    flush_or_rollback(db)
    return record


def get_thesis_snapshot_as_of(db, symbol, as_of_timestamp, snapshot_version=None):
    ensure_thesis_snapshot_table(db)
    query = (
        db.query(ThesisSnapshot)
        .filter(ThesisSnapshot.symbol == symbol)
        .filter(ThesisSnapshot.effective_timestamp <= _to_naive_utc(as_of_timestamp))
    )

    if snapshot_version:
        query = query.filter(ThesisSnapshot.snapshot_version == snapshot_version)

    return query.order_by(
        ThesisSnapshot.effective_timestamp.desc(),
        ThesisSnapshot.id.desc(),
    ).first()


def build_thesis_snapshot_leakage_diagnostics(snapshot, as_of_timestamp, expected_version=THESIS_SNAPSHOT_VERSION):
    as_of = _to_naive_utc(as_of_timestamp)
    if snapshot is None:
        return {
            "source": "thesis_snapshot_leakage_diagnostics",
            "as_of": as_of,
            "status": "PARTIAL",
            "violations": ["thesis snapshot missing"],
            "thesis_snapshot": {
                "found": False,
                "within_as_of": False,
                "version_matches": False,
                "expected_version": expected_version,
                "effective_timestamp": None,
                "source_timestamp": None,
                "lag_seconds": None,
            },
        }

    effective_timestamp = _to_naive_utc(getattr(snapshot, "effective_timestamp", None))
    source_timestamp = _to_naive_utc(getattr(snapshot, "source_timestamp", None))
    version = getattr(snapshot, "snapshot_version", None)
    within_as_of = as_of is None or effective_timestamp is None or effective_timestamp <= as_of
    lag_seconds = None
    if as_of is not None and effective_timestamp is not None:
        lag_seconds = round((as_of - effective_timestamp).total_seconds(), 3)

    violations = []
    if not within_as_of:
        violations.append("thesis snapshot is after as_of")
    if version != expected_version:
        violations.append("thesis snapshot version mismatch")

    return {
        "source": "thesis_snapshot_leakage_diagnostics",
        "as_of": as_of,
        "status": "PASS" if not violations else "FAIL",
        "violations": violations,
        "thesis_snapshot": {
            "found": True,
            "id": getattr(snapshot, "id", None),
            "thesis_id": getattr(snapshot, "thesis_id", None),
            "symbol": getattr(snapshot, "symbol", None),
            "side": getattr(snapshot, "side", None),
            "effective_timestamp": effective_timestamp,
            "source_timestamp": source_timestamp,
            "version": version,
            "expected_version": expected_version,
            "version_matches": version == expected_version,
            "within_as_of": within_as_of,
            "lag_seconds": lag_seconds,
        },
    }


def serialize_thesis_snapshot(record):
    if record is None:
        return None

    try:
        snapshot = json.loads(record.snapshot_json) if record.snapshot_json else {}
    except (TypeError, ValueError):
        snapshot = {}

    return {
        "id": record.id,
        "thesis_id": record.thesis_id,
        "thesis_key": record.thesis_key,
        "symbol": record.symbol,
        "side": record.side,
        "lifecycle_state": record.lifecycle_state,
        "source_timestamp": record.source_timestamp,
        "effective_timestamp": record.effective_timestamp,
        "snapshot_version": record.snapshot_version,
        "snapshot": snapshot,
        "created_at": record.created_at,
    }
