"""Canonical fingerprints for replay and online decision parity checks."""

import hashlib
import json
from datetime import datetime, timezone


PARITY_CONTRACT_VERSION = "decision_parity_v1"


def decision_fingerprint(payload):
    canonical = _canonical_value(payload)
    encoded = json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_parity_record(inputs, decision):
    return {
        "contract_version": PARITY_CONTRACT_VERSION,
        "input_fingerprint": decision_fingerprint(inputs),
        "decision_fingerprint": decision_fingerprint(decision),
        "canonicalization": "SORTED_JSON_UTC_ISO_FLOAT_10DP",
    }


def _canonical_value(value):
    if isinstance(value, dict):
        return {
            str(key): _canonical_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, datetime):
        timestamp = value
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, float):
        return round(value, 10)
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if hasattr(value, "__dict__"):
        return _canonical_value(vars(value))
    return str(value)
