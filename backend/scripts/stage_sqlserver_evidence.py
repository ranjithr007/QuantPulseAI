import argparse
import json
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


from app.database.native_evidence_stage import export_all_tables
from app.database.native_evidence_stage import derive_cross_dialect_manifest
from app.database.native_evidence_stage import import_staged_evidence
from app.database.native_evidence_stage import load_manifest
from app.database.runtime import normalize_database_url


def main():
    parser = argparse.ArgumentParser(
        description="Stage SQL Server evidence with BCP or import it into PostgreSQL."
    )
    parser.add_argument("command", choices=("export", "inspect", "derive", "import"))
    parser.add_argument("--stage-dir", type=Path, required=True)
    parser.add_argument("--server", default=r"(localdb)\MSSQLLocalDB")
    parser.add_argument("--database", default="QuantPulseAI")
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--confirm-source-writes-paused", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--manifest-name", default="evidence-manifest.json")
    parser.add_argument("--output-manifest-name", default="evidence-manifest-v2.json")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    if args.command == "export":
        payload = export_all_tables(
            args.stage_dir,
            server=args.server,
            database=args.database,
            source_writes_paused=args.confirm_source_writes_paused,
        )
    elif args.command == "inspect":
        payload = load_manifest(args.stage_dir, args.manifest_name)
    elif args.command == "derive":
        payload = derive_cross_dialect_manifest(
            args.stage_dir,
            source_manifest_name=args.manifest_name,
            output_manifest_name=args.output_manifest_name,
        )
    else:
        target_url = os.getenv("QUANTPULSE_TARGET_DATABASE_URL", "").strip()
        if not target_url:
            raise RuntimeError("QUANTPULSE_TARGET_DATABASE_URL is required for import.")
        target = create_engine(normalize_database_url(target_url), pool_pre_ping=True)
        try:
            payload = import_staged_evidence(
                args.stage_dir,
                target,
                batch_size=args.batch_size,
                resume=args.resume,
                manifest_name=args.manifest_name,
            )
        finally:
            target.dispose()

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(payload, indent=2, default=str, sort_keys=True),
            encoding="utf-8",
        )
    print(
        json.dumps(
            {
                "command": args.command,
                "stage_dir": str(args.stage_dir),
                "table_count": payload.get("table_count", len(payload.get("imported", []))),
                "total_rows": payload.get("total_rows"),
                "matched": payload.get("matched"),
            }
        )
    )


if __name__ == "__main__":
    main()
