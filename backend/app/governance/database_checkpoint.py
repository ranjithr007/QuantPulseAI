import argparse
import hashlib
import json
import shutil
import tempfile
from datetime import datetime
from datetime import timezone
from pathlib import Path

from sqlalchemy import text

from app.database.sqlserver import USING_SQLITE_FALLBACK
from app.database.sqlserver import engine


CHECKPOINT_VERSION = "r0_pre_r1_database_checkpoint_v1"


def inspect_database(database_engine=engine):
    if database_engine.dialect.name != "mssql" or USING_SQLITE_FALLBACK:
        raise RuntimeError(
            "R0 requires an active SQL Server database; SQLite fallback cannot "
            "be used for the official pre-R1 checkpoint."
        )

    with database_engine.connect() as connection:
        identity = dict(
            connection.execute(
                text(
                    """
                    SELECT
                        DB_NAME() AS database_name,
                        @@SERVERNAME AS server_name,
                        CAST(SERVERPROPERTY('Edition') AS nvarchar(128)) AS edition,
                        CAST(SERVERPROPERTY('ProductVersion') AS nvarchar(128)) AS product_version,
                        CAST(SERVERPROPERTY('InstanceDefaultBackupPath') AS nvarchar(4000)) AS default_backup_path,
                        CAST(SERVERPROPERTY('InstanceDefaultDataPath') AS nvarchar(4000)) AS default_data_path
                    """
                )
            ).mappings().one()
        )
        database_state = dict(
            connection.execute(
                text(
                    """
                    SELECT
                        state_desc,
                        recovery_model_desc,
                        compatibility_level,
                        create_date
                    FROM sys.databases
                    WHERE name = DB_NAME()
                    """
                )
            ).mappings().one()
        )
        tables = [
            dict(row)
            for row in connection.execute(
                text(
                    """
                    SELECT
                        schema_name(t.schema_id) AS schema_name,
                        t.name AS table_name,
                        SUM(CASE WHEN p.index_id IN (0, 1) THEN p.rows ELSE 0 END) AS row_count
                    FROM sys.tables t
                    LEFT JOIN sys.partitions p ON p.object_id = t.object_id
                    GROUP BY t.schema_id, t.name
                    ORDER BY schema_name(t.schema_id), t.name
                    """
                )
            ).mappings()
        ]
        columns = [
            dict(row)
            for row in connection.execute(
                text(
                    """
                    SELECT
                        schema_name(t.schema_id) AS schema_name,
                        t.name AS table_name,
                        c.column_id,
                        c.name AS column_name,
                        ty.name AS data_type,
                        c.max_length,
                        c.precision,
                        c.scale,
                        c.is_nullable,
                        c.is_identity
                    FROM sys.tables t
                    JOIN sys.columns c ON c.object_id = t.object_id
                    JOIN sys.types ty ON ty.user_type_id = c.user_type_id
                    ORDER BY schema_name(t.schema_id), t.name, c.column_id
                    """
                )
            ).mappings()
        ]
        indexes = [
            dict(row)
            for row in connection.execute(
                text(
                    """
                    SELECT
                        schema_name(t.schema_id) AS schema_name,
                        t.name AS table_name,
                        i.name AS index_name,
                        i.is_unique,
                        i.is_primary_key,
                        i.type_desc
                    FROM sys.tables t
                    JOIN sys.indexes i ON i.object_id = t.object_id
                    WHERE i.index_id > 0
                    ORDER BY schema_name(t.schema_id), t.name, i.name
                    """
                )
            ).mappings()
        ]
        alembic_versions = _alembic_versions(connection, tables)

    schema_payload = {
        "tables": tables,
        "columns": columns,
        "indexes": indexes,
        "alembic_versions": alembic_versions,
    }
    schema_json = json.dumps(
        schema_payload,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "identity": identity,
        "database_state": database_state,
        "schema": schema_payload,
        "schema_sha256": hashlib.sha256(schema_json).hexdigest(),
        "total_table_rows": sum(int(item.get("row_count") or 0) for item in tables),
    }


def create_verified_checkpoint(output_dir, database_engine=engine, *, as_of=None):
    inspected = inspect_database(database_engine)
    timestamp = _as_utc(as_of)
    output_root = Path(output_dir).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    stamp = timestamp.strftime("%Y%m%d_%H%M%S")
    database_name = str(inspected["identity"]["database_name"])
    safe_database_name = _safe_name(database_name)
    backup_path = output_root / f"{safe_database_name}_pre_r1_{stamp}.bak"
    checkpoint_path = output_root / f"{safe_database_name}_pre_r1_{stamp}.json"
    server_staging_path = (
        inspected["identity"].get("default_backup_path")
        or inspected["identity"].get("default_data_path")
    )
    staging_root = (
        Path(server_staging_path)
        if server_staging_path
        else Path(tempfile.gettempdir())
    )
    if not staging_root.exists():
        raise RuntimeError(
            f"SQL Server staging path does not exist: {staging_root}"
        )
    staging_backup_path = staging_root / backup_path.name

    _backup_database(database_engine, database_name, staging_backup_path)
    _verify_backup(database_engine, staging_backup_path)
    shutil.copy2(staging_backup_path, backup_path)
    backup_bytes = backup_path.read_bytes()
    staging_bytes = staging_backup_path.read_bytes()
    if hashlib.sha256(backup_bytes).digest() != hashlib.sha256(staging_bytes).digest():
        raise RuntimeError("Copied R0 database backup checksum does not match verified source")
    staging_backup_path.unlink()
    backup_record = {
        "path": str(backup_path),
        "bytes": len(backup_bytes),
        "sha256": hashlib.sha256(backup_bytes).hexdigest(),
        "restore_verifyonly": "PASS",
        "workspace_copy_checksum": "PASS",
    }
    checkpoint = {
        "checkpoint_version": CHECKPOINT_VERSION,
        "created_at": timestamp.isoformat(),
        "status": "VERIFIED",
        "purpose": "PRE_R1_CANONICAL_CANDLE_MIGRATION",
        "identity": inspected["identity"],
        "database_state": inspected["database_state"],
        "schema_sha256": inspected["schema_sha256"],
        "table_count": len(inspected["schema"]["tables"]),
        "total_table_rows": inspected["total_table_rows"],
        "alembic_versions": inspected["schema"]["alembic_versions"],
        "table_row_counts": inspected["schema"]["tables"],
        "backup": backup_record,
    }
    checkpoint_path.write_text(
        json.dumps(checkpoint, indent=2, default=str),
        encoding="utf-8",
    )
    return checkpoint, checkpoint_path


def _backup_database(database_engine, database_name, backup_path):
    database_identifier = database_name.replace("]", "]]")
    backup_literal = str(Path(backup_path).resolve()).replace("'", "''")
    statement = (
        f"BACKUP DATABASE [{database_identifier}] "
        f"TO DISK = N'{backup_literal}' "
        "WITH COPY_ONLY, INIT, CHECKSUM, STATS = 10"
    )
    _execute_maintenance_statement(database_engine, statement)


def _verify_backup(database_engine, backup_path):
    backup_literal = str(Path(backup_path).resolve()).replace("'", "''")
    statement = (
        f"RESTORE VERIFYONLY FROM DISK = N'{backup_literal}' WITH CHECKSUM"
    )
    _execute_maintenance_statement(database_engine, statement)


def _execute_maintenance_statement(database_engine, statement):
    raw_connection = database_engine.raw_connection()
    try:
        driver_connection = getattr(
            raw_connection,
            "driver_connection",
            raw_connection,
        )
        driver_connection.rollback()
        driver_connection.autocommit = True
        cursor = driver_connection.cursor()
        try:
            cursor.execute(statement)
            while cursor.nextset():
                pass
        finally:
            cursor.close()
    finally:
        raw_connection.close()


def _alembic_versions(connection, tables):
    if not any(
        str(item.get("table_name", "")).lower() == "alembic_version"
        for item in tables
    ):
        return []
    return [
        row[0]
        for row in connection.execute(
            text("SELECT version_num FROM alembic_version ORDER BY version_num")
        )
    ]


def _as_utc(value=None):
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _safe_name(value):
    return (
        "".join(
            character
            if character.isalnum() or character in {"-", "_"}
            else "_"
            for character in str(value or "")
        )
        or "database"
    )


def _default_output_dir():
    return Path(__file__).resolve().parents[3] / "outputs" / "r0_database_checkpoints"


def main():
    parser = argparse.ArgumentParser(
        description="Capture and verify the SQL Server checkpoint required before R1."
    )
    parser.add_argument(
        "--inspect-only",
        action="store_true",
        help="Print database identity and schema fingerprint without creating a backup.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(_default_output_dir()),
        help="Directory for the .bak file and checkpoint JSON.",
    )
    arguments = parser.parse_args()

    if arguments.inspect_only:
        inspected = inspect_database()
        print(
            json.dumps(
                {
                    "identity": inspected["identity"],
                    "database_state": inspected["database_state"],
                    "schema_sha256": inspected["schema_sha256"],
                    "table_count": len(inspected["schema"]["tables"]),
                    "total_table_rows": inspected["total_table_rows"],
                    "alembic_versions": inspected["schema"]["alembic_versions"],
                },
                indent=2,
                default=str,
            )
        )
        return

    checkpoint, checkpoint_path = create_verified_checkpoint(arguments.output_dir)
    print(
        json.dumps(
            {
                "status": checkpoint["status"],
                "checkpoint_path": str(checkpoint_path),
                "backup": checkpoint["backup"],
                "schema_sha256": checkpoint["schema_sha256"],
                "table_count": checkpoint["table_count"],
                "total_table_rows": checkpoint["total_table_rows"],
            },
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":
    main()
