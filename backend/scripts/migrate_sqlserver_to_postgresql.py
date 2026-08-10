import argparse
import json
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


from app.database.evidence_migration import migrate_evidence
from app.database.evidence_migration import schema_inventory
from app.database.evidence_migration import validate_migration_endpoints
from app.database.runtime import normalize_database_url


def main():
    parser = argparse.ArgumentParser(
        description="Inventory or migrate canonical SQL Server evidence to PostgreSQL."
    )
    parser.add_argument("command", choices=("inventory", "migrate"))
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--confirm-source-writes-paused", action="store_true")
    args = parser.parse_args()

    source_url = os.getenv("QUANTPULSE_SOURCE_DATABASE_URL", "").strip()
    target_url = os.getenv("QUANTPULSE_TARGET_DATABASE_URL", "").strip()
    if not source_url:
        raise RuntimeError("QUANTPULSE_SOURCE_DATABASE_URL is required.")

    source = create_engine(normalize_database_url(source_url), pool_pre_ping=True)
    try:
        if args.command == "inventory":
            payload = {
                "source_backend": source.url.get_backend_name(),
                "inventory": schema_inventory(source),
            }
        else:
            if not target_url:
                raise RuntimeError("QUANTPULSE_TARGET_DATABASE_URL is required.")
            target = create_engine(normalize_database_url(target_url), pool_pre_ping=True)
            try:
                validate_migration_endpoints(source, target)
                payload = migrate_evidence(
                    source,
                    target,
                    source_writes_paused=args.confirm_source_writes_paused,
                    batch_size=args.batch_size,
                )
            finally:
                target.dispose()
    finally:
        source.dispose()

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"report": str(args.report), "command": args.command}))


if __name__ == "__main__":
    main()
