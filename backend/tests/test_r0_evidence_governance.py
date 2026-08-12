import json
from datetime import datetime
from datetime import timezone

from app.governance.evidence_manifest import build_r0_evidence_manifest
from app.governance.evidence_policy import CURRENT_EVIDENCE_STATUS
from app.governance.evidence_policy import LEGACY_EVIDENCE_STATUS
from app.governance.evidence_policy import govern_phase2_report
from app.governance.evidence_policy import r0_evidence_governance
from app.governance.evidence_policy import r0_runtime_policy


def test_r0_runtime_policy_is_paper_only_and_blocks_promotion_and_ml():
    policy = r0_runtime_policy()

    assert policy["execution_scope"] == "PAPER_ONLY"
    assert policy["live_execution_enabled"] is False
    assert policy["promotion_enabled"] is False
    assert policy["ml_authority_enabled"] is False
    assert policy["official_entry_timeframes"] == ["1h", "2h", "4h", "1d"]


def test_r0_marks_old_artifacts_legacy_and_current_reports_research_only():
    legacy = r0_evidence_governance("2026-07-20T05:00:00+00:00")
    current = r0_evidence_governance(datetime(2026, 7, 26, 12, tzinfo=timezone.utc))

    assert legacy["evidence_status"] == LEGACY_EVIDENCE_STATUS
    assert legacy["legacy_artifact"] is True
    assert current["evidence_status"] == CURRENT_EVIDENCE_STATUS
    assert current["legacy_artifact"] is False


def test_phase2_report_preserves_assessment_but_blocks_promotion():
    report = govern_phase2_report(
        {
            "overall_status": "PASS",
            "next_action": "Promote this scope",
        },
        recorded_at="2026-07-20T05:00:00+00:00",
    )

    assert report["overall_status"] == "PASS"
    assert report["assessment_status"] == "PASS"
    assert report["promotion_allowed"] is False
    assert report["promotion_status"] == "BLOCKED_R0"
    assert report["official_claim_allowed"] is False
    assert report["evidence_status"] == LEGACY_EVIDENCE_STATUS
    assert "R1-R4" in report["next_action"]


def test_manifest_hashes_and_marks_each_saved_artifact(tmp_path):
    artifact_dir = tmp_path / "phase2_validation_reports"
    artifact_dir.mkdir()
    payload = {
        "saved_at": "2026-07-20T05:00:00+00:00",
        "scope": {"symbol": "DOGEUSDT", "timeframe": "1h", "signal": "SHORT"},
        "report": {
            "report_version": "phase2_validation_report_v1",
            "overall_status": "PASS",
            "walk_forward": {
                "contract": {"contract_version": "phase2_proof_of_edge_v1"},
            },
        },
        "walk_forward_result": {
            "strategy": "RESEARCH_ONLY",
            "strategy_metadata": {"fee_bps": 4, "slippage_bps": 2},
        },
    }
    (artifact_dir / "DOGEUSDT_1h_SHORT_test.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )
    (artifact_dir / "DOGEUSDT_1h_SHORT_test.md").write_text(
        "# test",
        encoding="utf-8",
    )

    manifest = build_r0_evidence_manifest(artifact_dir)

    assert manifest["artifact_set"]["artifact_count"] == 1
    assert manifest["artifact_set"]["file_count"] == 2
    assert len(manifest["artifact_set"]["aggregate_sha256"]) == 64
    assert manifest["records"][0]["governance"]["evidence_status"] == LEGACY_EVIDENCE_STATUS
    assert manifest["records"][0]["lineage"]["dataset_version"] == "UNRECORDED"
    assert manifest["database_snapshot"]["status"] == "PENDING_OPERATOR_BACKUP"


def test_manifest_attaches_only_a_verified_database_checkpoint(tmp_path):
    artifact_dir = tmp_path / "phase2_validation_reports"
    artifact_dir.mkdir()
    checkpoint = {
        "status": "VERIFIED",
        "checkpoint_version": "r0_pre_r1_database_checkpoint_v1",
        "created_at": "2026-07-26T18:00:00+00:00",
        "purpose": "PRE_R1_CANONICAL_CANDLE_MIGRATION",
        "identity": {"database_name": "QuantPulseAI"},
        "schema_sha256": "abc123",
        "table_count": 10,
        "total_table_rows": 100,
        "backup": {
            "path": "checkpoint.bak",
            "bytes": 2048,
            "sha256": "def456",
            "restore_verifyonly": "PASS",
        },
    }

    manifest = build_r0_evidence_manifest(
        artifact_dir,
        database_checkpoint=checkpoint,
    )

    assert manifest["database_snapshot"]["status"] == "VERIFIED"
    assert manifest["database_snapshot"]["schema_sha256"] == "abc123"
    assert manifest["database_snapshot"]["backup"]["restore_verifyonly"] == "PASS"
