import json
from datetime import datetime
from datetime import timezone

from app.features.feature_factory import build_features
from app.features.feature_factory import order_candles_for_features
from app.repositories.candle_repository import get_candles_as_of
from app.repositories.point_in_time_snapshot_repository import get_decision_snapshot_as_of
from app.repositories.point_in_time_snapshot_repository import get_feature_snapshot_as_of
from app.repositories.thesis_snapshot_repository import build_thesis_snapshot_leakage_diagnostics
from app.repositories.thesis_snapshot_repository import get_thesis_snapshot_as_of
from app.repositories.thesis_snapshot_repository import serialize_thesis_snapshot
from app.repositories.point_in_time_snapshot_repository import save_decision_snapshot
from app.repositories.point_in_time_snapshot_repository import save_feature_snapshot
from app.utils.freshness import normalize_timestamp_to_utc

FEATURE_VERSION = "feature_factory_v1"
DECISION_VERSION = "decision_contract_v1"


class PointInTimeLeakageError(ValueError):
    pass


def _to_naive_utc(timestamp):
    if timestamp is None:
        return None

    normalized = normalize_timestamp_to_utc(timestamp)
    if normalized is None:
        return None
    if normalized.tzinfo is not None:
        return normalized.astimezone(timezone.utc).replace(tzinfo=None)
    return normalized


def _ensure_point_in_time_candles(candles, effective_timestamp, symbol, timeframe):
    normalized_effective = _to_naive_utc(
        effective_timestamp
        or (candles[-1].candle_time if candles else datetime.utcnow())
    )

    if normalized_effective is None:
        return normalized_effective

    for candle in candles:
        candle_time = _to_naive_utc(getattr(candle, "candle_time", None))
        if candle_time is None:
            raise PointInTimeLeakageError(
                f"{symbol}/{timeframe} contains a candle without candle_time"
            )
        if candle_time > normalized_effective:
            raise PointInTimeLeakageError(
                f"{symbol}/{timeframe} leakage detected: candle_time {candle_time.isoformat()} "
                f"is after snapshot effective time {normalized_effective.isoformat()}"
            )

    return normalized_effective


def build_feature_snapshot(
    symbol, timeframe, candles, *, source_timestamp=None, effective_timestamp=None
):
    ordered_candles = order_candles_for_features(candles)
    candle_timestamp = ordered_candles[-1].candle_time if ordered_candles else None
    effective_ts = _ensure_point_in_time_candles(
        ordered_candles,
        effective_timestamp or candle_timestamp or datetime.utcnow(),
        symbol,
        timeframe,
    )
    feature = build_features(symbol, timeframe, ordered_candles)
    source_ts = _to_naive_utc(source_timestamp or candle_timestamp or effective_ts)

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "source_timestamp": source_ts,
        "effective_timestamp": effective_ts,
        "feature_version": FEATURE_VERSION,
        "quality_state": feature.get("quality", {}).get("status", "UNKNOWN"),
        "feature": feature,
    }


def build_decision_snapshot(
    symbol,
    timeframe,
    *,
    decision,
    source_timestamp=None,
    effective_timestamp=None,
    feature_version=FEATURE_VERSION,
    quality_state="UNKNOWN",
    confidence=None,
    regime=None,
    thesis_id=None,
    signal=None,
    trade_plan=None,
    context=None,
):
    effective_ts = _to_naive_utc(
        effective_timestamp or source_timestamp or datetime.utcnow()
    )
    source_ts = _to_naive_utc(source_timestamp or effective_ts)

    snapshot = {
        "symbol": symbol,
        "timeframe": timeframe,
        "source_timestamp": source_ts,
        "effective_timestamp": effective_ts,
        "feature_version": feature_version,
        "decision_version": DECISION_VERSION,
        "quality_state": quality_state,
        "decision": decision,
        "confidence": confidence,
        "regime": regime,
        "thesis_id": thesis_id,
    }

    if signal is not None:
        snapshot["signal"] = signal
    if trade_plan is not None:
        snapshot["trade_plan"] = trade_plan
    if context is not None:
        snapshot["context"] = context

    return snapshot


def persist_feature_snapshot(db, snapshot):
    return save_feature_snapshot(db, snapshot)


def persist_decision_snapshot(db, snapshot):
    return save_decision_snapshot(db, snapshot)


def build_point_in_time_leakage_diagnostics(
    *,
    as_of_timestamp,
    feature_snapshot=None,
    decision_snapshot=None,
    expected_feature_version=FEATURE_VERSION,
    expected_decision_version=DECISION_VERSION,
):
    as_of = _to_naive_utc(as_of_timestamp)

    def _snapshot_check(snapshot, kind, version_field, expected_version):
        if snapshot is None:
            return {
                "kind": kind,
                "found": False,
                "within_as_of": False,
                "version_matches": False,
                "expected_version": expected_version,
                "effective_timestamp": None,
                "source_timestamp": None,
                "lag_seconds": None,
            }

        effective_timestamp = _to_naive_utc(
            getattr(snapshot, "effective_timestamp", None)
        )
        source_timestamp = _to_naive_utc(getattr(snapshot, "source_timestamp", None))
        version = getattr(snapshot, version_field, None)
        within_as_of = (
            as_of is None or effective_timestamp is None or effective_timestamp <= as_of
        )
        lag_seconds = None
        if as_of is not None and effective_timestamp is not None:
            lag_seconds = round((as_of - effective_timestamp).total_seconds(), 3)

        return {
            "kind": kind,
            "found": True,
            "id": getattr(snapshot, "id", None),
            "symbol": getattr(snapshot, "symbol", None),
            "timeframe": getattr(snapshot, "timeframe", None),
            "effective_timestamp": effective_timestamp,
            "source_timestamp": source_timestamp,
            "version": version,
            "expected_version": expected_version,
            "version_matches": version == expected_version,
            "within_as_of": within_as_of,
            "lag_seconds": lag_seconds,
        }

    feature_check = _snapshot_check(
        feature_snapshot,
        "feature",
        "feature_version",
        expected_feature_version,
    )
    decision_check = _snapshot_check(
        decision_snapshot,
        "decision",
        "decision_version",
        expected_decision_version,
    )

    violations = []
    for item in (feature_check, decision_check):
        if item["found"] and not item["within_as_of"]:
            violations.append(f"{item['kind']} snapshot is after as_of")
        if item["found"] and not item["version_matches"]:
            violations.append(f"{item['kind']} snapshot version mismatch")

    status = "PASS" if not violations else "FAIL"
    if not feature_check["found"] or not decision_check["found"]:
        status = "PARTIAL" if not violations else "FAIL"

    return {
        "source": "point_in_time_leakage_diagnostics",
        "as_of": as_of,
        "status": status,
        "violations": violations,
        "feature": feature_check,
        "decision": decision_check,
    }


def build_features_as_of(db, symbol, timeframe, as_of_timestamp, *, limit=200):
    snapshot = get_feature_snapshot_as_of(db, symbol, timeframe, as_of_timestamp)
    if snapshot is not None:
        try:
            return json.loads(snapshot.snapshot_json)
        except (TypeError, ValueError, AttributeError):
            return None

    candles = get_candles_as_of(db, symbol, timeframe, as_of_timestamp, limit=limit)
    if not candles:
        return None

    return build_feature_snapshot(
        symbol,
        timeframe,
        candles,
        source_timestamp=as_of_timestamp,
        effective_timestamp=as_of_timestamp,
    )


def build_point_in_time_bundle(db, symbol, timeframe, as_of_timestamp):
    feature = get_feature_snapshot_as_of(db, symbol, timeframe, as_of_timestamp)
    decision = get_decision_snapshot_as_of(db, symbol, timeframe, as_of_timestamp)
    thesis = get_thesis_snapshot_as_of(db, symbol, as_of_timestamp)

    return {
        "feature_snapshot": feature,
        "decision_snapshot": decision,
        "thesis_snapshot": thesis,
        "feature_leakage_diagnostics": build_point_in_time_leakage_diagnostics(
            as_of_timestamp=as_of_timestamp,
            feature_snapshot=feature,
            decision_snapshot=decision,
        ),
        "thesis_leakage_diagnostics": build_thesis_snapshot_leakage_diagnostics(
            thesis,
            as_of_timestamp,
        ),
        "serialized": {
            "feature_snapshot": None if feature is None else json.loads(feature.snapshot_json),
            "decision_snapshot": None if decision is None else json.loads(decision.snapshot_json),
            "thesis_snapshot": serialize_thesis_snapshot(thesis),
        },
    }
