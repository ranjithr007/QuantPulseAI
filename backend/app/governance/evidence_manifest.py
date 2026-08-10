import hashlib
import json
from datetime import datetime
from datetime import timezone
from pathlib import Path

from app.governance.evidence_policy import R0_POLICY_VERSION
from app.governance.evidence_policy import R0_RECOVERY_GATE
from app.governance.evidence_policy import r0_evidence_governance
from app.governance.evidence_policy import r0_runtime_policy


MANIFEST_VERSION = "r0_evidence_manifest_v1"


def build_r0_evidence_manifest(artifact_dir, *, database_checkpoint=None):
    artifact_root = Path(artifact_dir)
    records = []
    aggregate_lines = []

    for json_path in sorted(artifact_root.glob("*.json")):
        payload = _read_json(json_path)
        if not payload:
            continue
        markdown_path = json_path.with_suffix(".md")
        saved_at = payload.get("saved_at")
        report = dict(payload.get("report") or {})
        walk_forward = dict(payload.get("walk_forward_result") or {})
        strategy_metadata = dict(
            walk_forward.get("strategy_metadata")
            or dict(report.get("walk_forward") or {}).get("strategy_metadata")
            or {}
        )
        json_file = _file_record(json_path)
        markdown_file = _file_record(markdown_path) if markdown_path.exists() else None
        aggregate_lines.append(f"{json_file['name']}:{json_file['sha256']}")
        if markdown_file:
            aggregate_lines.append(f"{markdown_file['name']}:{markdown_file['sha256']}")

        records.append(
            {
                "artifact_id": json_path.stem,
                "saved_at": saved_at,
                "scope": payload.get("scope") or report.get("scope") or {},
                "governance": r0_evidence_governance(saved_at),
                "assessment": {
                    "overall_status": report.get("overall_status"),
                    "architecture_gate_status": dict(
                        report.get("architecture_gate") or {}
                    ).get("status"),
                    "report_version": report.get("report_version"),
                },
                "lineage": {
                    "validation_contract_version": dict(
                        dict(report.get("walk_forward") or {}).get("contract") or {}
                    ).get("contract_version"),
                    "strategy": walk_forward.get("strategy")
                    or dict(report.get("walk_forward") or {}).get("strategy"),
                    "strategy_metadata": strategy_metadata,
                    "dataset_version": "UNRECORDED",
                    "feature_version": strategy_metadata.get("feature_version")
                    or "UNRECORDED",
                    "cost_model": {
                        "fee_bps": strategy_metadata.get("fee_bps", "UNRECORDED"),
                        "slippage_bps": strategy_metadata.get(
                            "slippage_bps",
                            "UNRECORDED",
                        ),
                    },
                    "code_revision": "UNRECORDED",
                },
                "files": {
                    "json": json_file,
                    "markdown": markdown_file,
                },
            }
        )

    aggregate_text = "\n".join(sorted(aggregate_lines)).encode("utf-8")
    total_bytes = sum(
        file_record["bytes"]
        for record in records
        for file_record in record["files"].values()
        if file_record
    )
    return {
        "manifest_version": MANIFEST_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "policy": r0_runtime_policy(),
        "recovery_gate": R0_RECOVERY_GATE,
        "policy_version": R0_POLICY_VERSION,
        "artifact_set": {
            "directory": str(artifact_root.resolve()),
            "artifact_count": len(records),
            "file_count": len(aggregate_lines),
            "total_bytes": total_bytes,
            "aggregate_sha256": hashlib.sha256(aggregate_text).hexdigest(),
        },
        "database_snapshot": _database_snapshot(database_checkpoint),
        "records": records,
    }


def write_r0_evidence_manifest(
    artifact_dir,
    output_path,
    *,
    database_checkpoint=None,
):
    manifest = build_r0_evidence_manifest(
        artifact_dir,
        database_checkpoint=database_checkpoint,
    )
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(manifest, indent=2, default=str),
        encoding="utf-8",
    )
    return manifest


def _file_record(path):
    value = Path(path)
    content = value.read_bytes()
    return {
        "name": value.name,
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return None


def _database_snapshot(checkpoint):
    if checkpoint and checkpoint.get("status") == "VERIFIED":
        return {
            "status": "VERIFIED",
            "checkpoint_version": checkpoint.get("checkpoint_version"),
            "created_at": checkpoint.get("created_at"),
            "purpose": checkpoint.get("purpose"),
            "identity": checkpoint.get("identity") or {},
            "schema_sha256": checkpoint.get("schema_sha256"),
            "table_count": checkpoint.get("table_count"),
            "total_table_rows": checkpoint.get("total_table_rows"),
            "backup": checkpoint.get("backup") or {},
        }
    return {
        "status": "PENDING_OPERATOR_BACKUP",
        "reason": (
            "A SQL Server backup/checkpoint must be captured before the R1 "
            "market-candle migration and data rebuild."
        ),
    }


def _latest_verified_checkpoint(outputs_root):
    checkpoint_dir = Path(outputs_root) / "r0_database_checkpoints"
    for path in sorted(checkpoint_dir.glob("*.json"), reverse=True):
        checkpoint = _read_json(path)
        if checkpoint and checkpoint.get("status") == "VERIFIED":
            return checkpoint
    return None


def _default_outputs_root():
    return Path(__file__).resolve().parents[3] / "outputs"


if __name__ == "__main__":
    outputs_root = _default_outputs_root()
    database_checkpoint = _latest_verified_checkpoint(outputs_root)
    manifest = write_r0_evidence_manifest(
        outputs_root / "phase2_validation_reports",
        outputs_root / "r0_evidence_manifest_2026-07-26.json",
        database_checkpoint=database_checkpoint,
    )
    print(
        json.dumps(
            {
                "manifest_version": manifest["manifest_version"],
                "artifact_count": manifest["artifact_set"]["artifact_count"],
                "file_count": manifest["artifact_set"]["file_count"],
                "aggregate_sha256": manifest["artifact_set"]["aggregate_sha256"],
                "database_snapshot": manifest["database_snapshot"]["status"],
            },
            indent=2,
        )
    )
