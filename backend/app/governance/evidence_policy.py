from datetime import datetime
from datetime import timezone


R0_POLICY_VERSION = "r0_truth_repair_policy_v1"
R0_RECOVERY_GATE = "R0_TRUTH_REPAIR"
R0_EFFECTIVE_AT = datetime(2026, 7, 26, tzinfo=timezone.utc)

LEGACY_EVIDENCE_STATUS = "LEGACY_INVALIDATED_DATA_V1"
CURRENT_EVIDENCE_STATUS = "R0_RESEARCH_ONLY_DATA_UNVERIFIED"
OFFICIAL_ENTRY_TIMEFRAMES = ("1h", "2h", "4h", "1d")
MIN_ENTRY_CONFIDENCE = 40.0
FULL_SIZE_ENTRY_CONFIDENCE = 60.0
MINIMUM_TIER_RISK_PERCENT = 0.5


def r0_runtime_policy():
    return {
        "policy_version": R0_POLICY_VERSION,
        "recovery_gate": R0_RECOVERY_GATE,
        "execution_scope": "PAPER_ONLY",
        "live_execution_enabled": False,
        "promotion_enabled": False,
        "ml_authority_enabled": False,
        "official_entry_timeframes": list(OFFICIAL_ENTRY_TIMEFRAMES),
        "min_entry_confidence": MIN_ENTRY_CONFIDENCE,
        "full_size_entry_confidence": FULL_SIZE_ENTRY_CONFIDENCE,
        "minimum_tier_risk_percent": MINIMUM_TIER_RISK_PERCENT,
        "reason": (
            "Canonical candle finality and full point-in-time replay parity "
            "must pass R1-R4 before promotion can resume."
        ),
    }


def r0_evidence_governance(recorded_at=None):
    timestamp = _as_utc(recorded_at)
    legacy = timestamp is not None and timestamp < R0_EFFECTIVE_AT
    evidence_status = LEGACY_EVIDENCE_STATUS if legacy else CURRENT_EVIDENCE_STATUS
    return {
        **r0_runtime_policy(),
        "evidence_status": evidence_status,
        "recorded_at": timestamp.isoformat() if timestamp is not None else None,
        "promotion_allowed": False,
        "promotion_status": "BLOCKED_R0",
        "official_claim_allowed": False,
        "legacy_artifact": legacy,
        "required_repairs": [
            "canonical_final_candles",
            "point_in_time_effective_timestamps",
            "online_offline_replay_parity",
            "regenerated_phase2_evidence",
        ],
    }


def govern_phase2_report(report, *, recorded_at=None):
    governed = dict(report or {})
    timestamp = recorded_at or governed.get("generated_at")
    policy = r0_evidence_governance(timestamp)
    assessment_status = governed.get("assessment_status") or governed.get("overall_status")
    assessment_next_action = governed.get("assessment_next_action") or governed.get("next_action")

    governed.update(
        {
            "assessment_status": assessment_status,
            "assessment_next_action": assessment_next_action,
            "evidence_status": policy["evidence_status"],
            "promotion_allowed": False,
            "promotion_status": policy["promotion_status"],
            "official_claim_allowed": False,
            "evidence_governance": policy,
            "next_action": (
                "Complete R1-R4 truth repair and regenerate this evidence from "
                "canonical final candles before promotion review."
            ),
        }
    )
    return governed


def _as_utc(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        timestamp = value
    else:
        try:
            timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)
