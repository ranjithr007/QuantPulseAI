"""Outcome-blind V2F readiness for frozen entry-strategy holdout cohorts."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.database.models.strategy_shadow_trade import StrategyShadowTrade
from app.paper_trading.exit_evidence import read_evidence
from app.strategies.registry import STRATEGY_REGISTRY


READINESS_VERSION = "entry_strategy_holdout_readiness_v2f"
DEFAULT_MANIFEST_PATH = Path(__file__).with_name("entry_strategy_holdout_v2f.json")


def load_manifest(path=None):
    manifest_path = Path(path or DEFAULT_MANIFEST_PATH)
    raw = manifest_path.read_bytes()
    manifest = json.loads(raw.decode("utf-8"))
    validate_manifest(manifest)
    return manifest, hashlib.sha256(raw).hexdigest()


def collect_candidate_entries(session, manifest):
    """Select entry-only evidence; outcome and exit columns are never loaded."""

    validate_manifest(manifest)
    cutoff = _utc(manifest["holdout_start_exclusive"]).replace(tzinfo=None)
    pairs = {
        (item["strategy_id"], item["strategy_version"])
        for item in manifest["candidates"]
    }
    strategy_ids = sorted({item[0] for item in pairs})
    rows = (
        session.query(
            StrategyShadowTrade.id,
            StrategyShadowTrade.strategy_id,
            StrategyShadowTrade.strategy_version,
            StrategyShadowTrade.symbol,
            StrategyShadowTrade.side,
            StrategyShadowTrade.entry_timeframe,
            StrategyShadowTrade.opened_at,
            StrategyShadowTrade.execution_evidence_json,
        )
        .filter(StrategyShadowTrade.opened_at > cutoff)
        .filter(StrategyShadowTrade.strategy_id.in_(strategy_ids))
        .order_by(StrategyShadowTrade.opened_at, StrategyShadowTrade.id)
        .all()
    )
    return [
        {
            "trade_id": row.id,
            "strategy_id": row.strategy_id,
            "strategy_version": row.strategy_version,
            "symbol": row.symbol,
            "side": row.side,
            "entry_timeframe": row.entry_timeframe,
            "opened_at": row.opened_at,
            "execution_evidence": read_evidence(row.execution_evidence_json),
        }
        for row in rows
        if (row.strategy_id, row.strategy_version) in pairs
    ]


def assess_entry_holdout_readiness(
    entries,
    manifest,
    *,
    observed_at=None,
    manifest_sha256=None,
):
    """Count frozen post-cutoff samples without reading or reporting outcomes."""

    validate_manifest(manifest)
    observed = _utc(observed_at or datetime.now(timezone.utc))
    cutoff = _utc(manifest["holdout_start_exclusive"])
    maturation_hours = int(manifest["maturation_hours"])
    mature_before = observed - timedelta(hours=maturation_hours)
    minimum_trades = int(manifest["minimum_mature_trades_per_candidate"])
    minimum_days = float(manifest["minimum_calendar_days"])
    expected_profile = manifest["required_entry_evidence"]["profile"]
    expected_pass = bool(manifest["required_entry_evidence"]["passed"])
    elapsed_days = max(0.0, (observed - cutoff).total_seconds() / 86400)

    cohorts = []
    for candidate in manifest["candidates"]:
        pair = (candidate["strategy_id"], candidate["strategy_version"])
        selected = [
            row
            for row in entries
            if (str(row.get("strategy_id") or ""), str(row.get("strategy_version") or ""))
            == pair
            and (_optional_utc(row.get("opened_at")) or cutoff) > cutoff
        ]
        mature = [
            row
            for row in selected
            if (_optional_utc(row.get("opened_at")) or observed) <= mature_before
        ]
        evidence_valid = [
            row
            for row in mature
            if _valid_entry_evidence(
                row.get("execution_evidence"), expected_profile, expected_pass
            )
        ]
        invalid_count = len(mature) - len(evidence_valid)
        candidate_ready = (
            elapsed_days >= minimum_days
            and len(evidence_valid) >= minimum_trades
            and invalid_count == 0
        )
        cohorts.append(
            {
                **candidate,
                "post_cutoff_entries": len(selected),
                "mature_entries": len(mature),
                "immature_entries": len(selected) - len(mature),
                "valid_mature_entry_evidence": len(evidence_valid),
                "invalid_mature_entry_evidence": invalid_count,
                "mature_trades_remaining": max(0, minimum_trades - len(evidence_valid)),
                "symbols": _distribution(evidence_valid, "symbol"),
                "sides": _distribution(evidence_valid, "side"),
                "timeframes": _distribution(evidence_valid, "entry_timeframe"),
                "readiness": "READY" if candidate_ready else "COLLECTING",
            }
        )

    invalid_evidence = sum(item["invalid_mature_entry_evidence"] for item in cohorts)
    all_ready = bool(cohorts) and all(item["readiness"] == "READY" for item in cohorts)
    if observed <= cutoff:
        status = "HOLDOUT_NOT_STARTED"
    elif invalid_evidence:
        status = "INVALID_ENTRY_EVIDENCE"
    elif all_ready:
        status = "OUTCOME_REVIEW_READY"
    else:
        status = "COLLECTING_PROSPECTIVE_ENTRIES"
    return {
        "contract": READINESS_VERSION,
        "status": status,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "observed_at": observed.isoformat(),
        "manifest": {
            "version": manifest["manifest_version"],
            "sha256": manifest_sha256,
            "frozen_at": manifest["frozen_at"],
            "holdout_start_exclusive": manifest["holdout_start_exclusive"],
        },
        "elapsed_calendar_days": round(elapsed_days, 4),
        "minimum_calendar_days": minimum_days,
        "maturation_hours": maturation_hours,
        "mature_entry_cutoff_inclusive": mature_before.isoformat(),
        "minimum_mature_trades_per_candidate": minimum_trades,
        "candidate_count": len(cohorts),
        "ready_candidate_count": sum(item["readiness"] == "READY" for item in cohorts),
        "outcome_review_unlocked": all_ready,
        "cohorts": cohorts,
        "governance": {
            "outcome_columns_accessed": False,
            "exit_columns_accessed": False,
            "automatic_promotion_allowed": False,
            "paper_policy_changed": False,
            "live_policy_changed": False,
            "next_action": (
                "Run the separately governed outcome evaluator once; do not auto-promote."
                if all_ready
                else "Continue unchanged paper collection without inspecting holdout outcomes."
            ),
        },
    }


def build_current_entry_holdout_readiness(session, *, observed_at=None, manifest_path=None):
    manifest, digest = load_manifest(manifest_path)
    entries = collect_candidate_entries(session, manifest)
    return assess_entry_holdout_readiness(
        entries,
        manifest,
        observed_at=observed_at,
        manifest_sha256=digest,
    )


def validate_manifest(manifest):
    required = {
        "manifest_version",
        "frozen_at",
        "holdout_start_exclusive",
        "maturation_hours",
        "minimum_calendar_days",
        "minimum_mature_trades_per_candidate",
        "required_entry_evidence",
        "outcome_gates",
        "candidates",
        "governance",
    }
    missing = required.difference(manifest)
    if missing:
        raise ValueError("Entry holdout manifest is missing: " + ", ".join(sorted(missing)))
    frozen = _utc(manifest["frozen_at"])
    cutoff = _utc(manifest["holdout_start_exclusive"])
    if frozen > cutoff:
        raise ValueError("Entry holdout must be frozen no later than its cutoff")
    if int(manifest["maturation_hours"]) <= 0:
        raise ValueError("Entry holdout maturation_hours must be positive")
    if float(manifest["minimum_calendar_days"]) <= 0:
        raise ValueError("Entry holdout minimum_calendar_days must be positive")
    if int(manifest["minimum_mature_trades_per_candidate"]) < 30:
        raise ValueError("Entry holdout requires at least 30 mature trades per candidate")
    evidence = manifest["required_entry_evidence"]
    if not str(evidence.get("profile") or "").strip() or evidence.get("passed") is not True:
        raise ValueError("Entry holdout requires a named, passed entry-evidence profile")
    gates = manifest["outcome_gates"]
    required_gates = {
        "minimum_win_rate_percent",
        "minimum_profit_factor_after_funding",
        "minimum_average_return_after_funding_percent_exclusive",
        "require_complete_funding_coverage",
        "require_target1_hits_greater_than_pre_t1_losing_stops",
    }
    if required_gates.difference(gates):
        raise ValueError("Entry holdout outcome gates are incomplete")
    if not 0 < float(gates["minimum_win_rate_percent"]) <= 100:
        raise ValueError("Entry holdout win-rate gate must be in (0, 100]")
    if float(gates["minimum_profit_factor_after_funding"]) <= 0:
        raise ValueError("Entry holdout profit-factor gate must be positive")
    if gates["require_complete_funding_coverage"] is not True:
        raise ValueError("Entry holdout requires complete stored funding coverage")
    if gates["require_target1_hits_greater_than_pre_t1_losing_stops"] is not True:
        raise ValueError("Entry holdout requires target successes to exceed pre-T1 losses")
    candidates = manifest["candidates"]
    if not candidates:
        raise ValueError("Entry holdout requires at least one candidate")
    pairs = set()
    for item in candidates:
        pair = (str(item.get("strategy_id") or ""), str(item.get("strategy_version") or ""))
        if not all(pair) or pair in pairs:
            raise ValueError("Entry holdout candidate pairs must be present and unique")
        pairs.add(pair)
        registered = STRATEGY_REGISTRY.get(pair[0])
        if not registered or registered.get("version") != pair[1]:
            raise ValueError(f"Entry holdout candidate is not the registered immutable version: {pair}")
        if not registered.get("immutable_experiment"):
            raise ValueError(f"Entry holdout candidate is not immutable: {pair}")
    governance = manifest["governance"]
    if any(
        governance.get(key) is not expected
        for key, expected in (
            ("research_only", True),
            ("outcome_blind_until_all_candidates_ready", True),
            ("automatic_promotion", False),
            ("paper_policy_change_authorized", False),
            ("live_policy_change_authorized", False),
        )
    ):
        raise ValueError("Entry holdout governance must remain research-only and outcome-blind")


def _valid_entry_evidence(value, expected_profile, expected_pass):
    evidence = read_evidence(value)
    return (
        evidence.get("entry_quality_profile") == expected_profile
        and evidence.get("entry_quality_passed") is expected_pass
    )


def _distribution(rows, field):
    counts = Counter(str(row.get(field) or "UNKNOWN").upper() for row in rows)
    return dict(sorted(counts.items()))


def _utc(value):
    parsed = _optional_utc(value)
    if parsed is None:
        raise ValueError(f"Invalid required timestamp: {value!r}")
    return parsed


def _optional_utc(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
