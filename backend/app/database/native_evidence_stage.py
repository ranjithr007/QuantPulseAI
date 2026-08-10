"""Native BCP staging for LocalDB sources that Python ODBC cannot open."""

import hashlib
import json
import re
import subprocess
import time as clock
from datetime import date, datetime, time, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, Numeric, Time, func, select

from app.database.evidence_migration import _canonical_value
from app.database.evidence_migration import _reset_postgresql_sequences
from app.database.evidence_migration import schema_inventory
from app.database.evidence_migration import validate_empty_target
from app.database.postgresql_baseline import POSTGRESQL_BASELINE_FINGERPRINT
from app.database.runtime import Base
from app.database import models as _models  # noqa: F401


MANIFEST_NAME = "evidence-manifest.json"


def build_bcp_query(table):
    table_name = _quote_identifier(table.name)
    primary_key = list(table.primary_key.columns)
    order_by = ""
    if primary_key:
        order_by = " ORDER BY " + ", ".join(
            f"source.{_quote_identifier(column.name)}" for column in primary_key
        )
    return (
        "SELECT (SELECT source.* FOR JSON PATH, INCLUDE_NULL_VALUES, "
        f"WITHOUT_ARRAY_WRAPPER) FROM dbo.{table_name} AS source{order_by}"
    )


def export_table_bcp(
    table,
    destination,
    *,
    server,
    database,
    bcp_executable="bcp",
    attempts=3,
    retry_delay_seconds=1.0,
):
    output = Path(destination)
    if output.exists():
        raise RuntimeError(f"Refusing to overwrite staged evidence: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        bcp_executable,
        build_bcp_query(table),
        "queryout",
        str(output),
        "-S",
        server,
        "-d",
        database,
        "-T",
        "-c",
        "-C",
        "65001",
        "-r",
        "\\n",
    ]
    if attempts < 1:
        raise ValueError("BCP export attempts must be at least 1.")
    failures = []
    result = None
    for attempt in range(1, attempts + 1):
        output.unlink(missing_ok=True)
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode == 0:
            break
        failures.append((result.stderr or result.stdout).strip())
        if attempt < attempts:
            clock.sleep(retry_delay_seconds)
    else:
        raise RuntimeError(
            f"BCP export failed for {table.name} after {attempts} attempt(s): "
            f"{failures[-1]}"
        )
    match = re.search(r"(\d+) rows copied", result.stdout)
    reported_rows = int(match.group(1)) if match else None
    evidence = staged_file_evidence(output, table)
    if reported_rows is not None and reported_rows != evidence["rows"]:
        raise RuntimeError(
            f"BCP row count mismatch for {table.name}: "
            f"reported {reported_rows}, staged {evidence['rows']}"
        )
    return evidence


def export_all_tables(
    stage_directory,
    *,
    server,
    database,
    source_writes_paused=False,
    bcp_executable="bcp",
):
    if not source_writes_paused:
        raise RuntimeError("BCP export requires source writes to be paused explicitly.")
    stage = Path(stage_directory)
    manifest_path = stage / MANIFEST_NAME
    if manifest_path.exists():
        raise RuntimeError(f"Refusing to overwrite evidence manifest: {manifest_path}")
    stage.mkdir(parents=True, exist_ok=True)

    records = []
    for table in Base.metadata.sorted_tables:
        filename = f"{table.name}.jsonl"
        evidence = export_table_bcp(
            table,
            stage / filename,
            server=server,
            database=database,
            bcp_executable=bcp_executable,
        )
        records.append({"table": table.name, "file": filename, **evidence})

    manifest = {
        "format": "quantpulse-bcp-jsonl-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": {"backend": "mssql", "server": server, "database": database},
        "schema_fingerprint": POSTGRESQL_BASELINE_FINGERPRINT,
        "table_count": len(records),
        "total_rows": sum(record["rows"] for record in records),
        "tables": records,
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return manifest


def staged_file_evidence(path, table):
    digest = hashlib.sha256()
    rows = 0
    for payload in iter_staged_rows(path, table):
        digest.update(_canonical_row_bytes(payload, table))
        rows += 1
    return {
        "rows": rows,
        "sha256": digest.hexdigest(),
        "bytes": Path(path).stat().st_size,
    }


def iter_staged_rows(path, table):
    expected = {column.name for column in table.columns}
    with Path(path).open("r", encoding="utf-8-sig", newline="") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"Invalid JSON in {path} at line {line_number}: {exc}"
                ) from exc
            actual = set(raw)
            if actual != expected:
                raise RuntimeError(
                    f"Staged columns differ for {table.name} at line {line_number}: "
                    f"missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
                )
            yield {
                column.name: _coerce_value(raw[column.name], column.type)
                for column in table.columns
            }


def load_manifest(stage_directory, manifest_name=MANIFEST_NAME):
    stage = Path(stage_directory)
    manifest = json.loads((stage / manifest_name).read_text(encoding="utf-8"))
    if manifest.get("format") != "quantpulse-bcp-jsonl-v1":
        raise RuntimeError("Unsupported staged evidence format.")
    if manifest.get("schema_fingerprint") != POSTGRESQL_BASELINE_FINGERPRINT:
        raise RuntimeError("Staged evidence schema fingerprint does not match PG2.")
    if manifest.get("table_count") != len(Base.metadata.tables):
        raise RuntimeError("Staged evidence does not contain all baseline tables.")
    expected_tables = set(Base.metadata.tables)
    actual_tables = {record["table"] for record in manifest.get("tables", [])}
    if actual_tables != expected_tables:
        raise RuntimeError("Staged evidence table set does not match PG2 baseline.")
    return manifest


def derive_cross_dialect_manifest(
    stage_directory,
    *,
    source_manifest_name=MANIFEST_NAME,
    output_manifest_name="evidence-manifest-v2.json",
):
    stage = Path(stage_directory)
    source_path = stage / source_manifest_name
    output_path = stage / output_manifest_name
    if output_path.exists():
        raise RuntimeError(f"Refusing to overwrite derived manifest: {output_path}")
    source_manifest = load_manifest(stage, source_manifest_name)
    source_records = {record["table"]: record for record in source_manifest["tables"]}
    records = []
    for table in Base.metadata.sorted_tables:
        source_record = source_records[table.name]
        evidence = _versioned_staged_file_evidence(stage / source_record["file"], table)
        for field in ("rows", "bytes", "legacy_sha256"):
            expected_field = "sha256" if field == "legacy_sha256" else field
            if evidence[field] != source_record[expected_field]:
                raise RuntimeError(
                    f"Original staged evidence changed for {table.name}: {field} mismatch."
                )
        records.append(
            {
                **source_record,
                "sha256": evidence["sha256"],
                "legacy_sha256": evidence["legacy_sha256"],
            }
        )
    derived = {
        **source_manifest,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "canonicalization": "cross-dialect-numeric-v2",
        "parent_manifest": source_manifest_name,
        "parent_manifest_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        "tables": records,
    }
    output_path.write_text(
        json.dumps(derived, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return derived


def import_staged_evidence(
    stage_directory,
    target_engine,
    *,
    batch_size=1000,
    resume=False,
    manifest_name=MANIFEST_NAME,
):
    if target_engine.url.get_backend_name() != "postgresql":
        raise RuntimeError("Staged evidence target must be PostgreSQL.")
    if resume:
        _validate_target_schema(target_engine)
    else:
        validate_empty_target(target_engine)
    stage = Path(stage_directory)
    manifest = load_manifest(stage, manifest_name)
    records_by_table = {record["table"]: record for record in manifest["tables"]}
    imported = []
    verified_target = {}

    for table in Base.metadata.sorted_tables:
        record = records_by_table[table.name]
        path = stage / record["file"]
        current_evidence = staged_file_evidence(path, table)
        for field in ("rows", "sha256", "bytes"):
            if current_evidence[field] != record[field]:
                raise RuntimeError(
                    f"Staged evidence changed for {table.name}: {field} mismatch."
                )

        with target_engine.connect() as connection:
            existing_rows = connection.execute(
                select(func.count()).select_from(table)
            ).scalar_one()
        target_engine.dispose()
        if existing_rows:
            if not resume:
                raise RuntimeError(
                    f"PostgreSQL migration target table is not empty: {table.name}."
                )
            existing = resilient_table_checksum(
                target_engine,
                table,
                batch_size=batch_size,
            )
            if existing["rows"] != record["rows"] or existing["sha256"] != record["sha256"]:
                raise RuntimeError(
                    f"Cannot resume {table.name}: committed target evidence differs."
                )
            verified_target[table.name] = existing
            imported.append({"table": table.name, "rows": existing_rows, "resumed": True})
            continue

        with target_engine.begin() as connection:
            copied = _copy_table_postgresql(connection, path, table)
            if copied != record["rows"]:
                raise RuntimeError(
                    f"Imported row count differs for {table.name}: "
                    f"expected {record['rows']}, got {copied}."
                )
        target_engine.dispose()
        imported.append({"table": table.name, "rows": copied, "resumed": False})

    with target_engine.begin() as connection:
        _reset_postgresql_sequences(connection)
    target_engine.dispose()

    reconciliation = []
    for table in Base.metadata.sorted_tables:
        expected = records_by_table[table.name]
        actual = verified_target.get(table.name)
        if actual is None:
            actual = resilient_table_checksum(
                target_engine,
                table,
                batch_size=batch_size,
            )
        matches = (
            actual["rows"] == expected["rows"]
            and actual["sha256"] == expected["sha256"]
        )
        reconciliation.append(
            {
                "table": table.name,
                "expected_rows": expected["rows"],
                "actual_rows": actual["rows"],
                "expected_sha256": expected["sha256"],
                "actual_sha256": actual["sha256"],
                "matches": matches,
            }
        )
    if not all(record["matches"] for record in reconciliation):
        raise RuntimeError("PostgreSQL staged evidence reconciliation failed.")
    return {
        "imported": imported,
        "total_rows": sum(record["rows"] for record in imported),
        "reconciliation": reconciliation,
        "matched": True,
    }


def _copy_table_postgresql(connection, path, table):
    preparer = connection.dialect.identifier_preparer
    relation = preparer.format_table(table)
    columns = ", ".join(preparer.quote(column.name) for column in table.columns)
    statement = f"COPY {relation} ({columns}) FROM STDIN"
    driver_connection = connection.connection.driver_connection
    copied = 0
    with driver_connection.cursor().copy(statement) as copy:
        for row in iter_staged_rows(path, table):
            copy.write_row(tuple(row[column.name] for column in table.columns))
            copied += 1
    return copied


def resilient_table_checksum(
    target_engine,
    table,
    *,
    batch_size=5000,
    attempts=12,
    retry_delay_seconds=15,
):
    primary_keys = list(table.primary_key.columns)
    if len(primary_keys) != 1:
        raise RuntimeError(
            f"Resilient checksum requires one primary key column: {table.name}."
        )
    primary_key = primary_keys[0]
    digest = hashlib.sha256()
    row_count = 0
    last_primary_key = None

    while True:
        statement = select(table).order_by(primary_key).limit(batch_size)
        if last_primary_key is not None:
            statement = statement.where(primary_key > last_primary_key)

        rows = None
        for attempt in range(1, attempts + 1):
            try:
                with target_engine.connect() as connection:
                    rows = list(connection.execute(statement).mappings())
                break
            except Exception:
                target_engine.dispose()
                if attempt == attempts:
                    raise
                clock.sleep(retry_delay_seconds)

        if not rows:
            break
        for row in rows:
            digest.update(_canonical_row_bytes(row, table))
            row_count += 1
        last_primary_key = rows[-1][primary_key.name]

    return {"rows": row_count, "sha256": digest.hexdigest()}


def _validate_target_schema(target_engine):
    inventory = schema_inventory(target_engine)
    missing = [record["table"] for record in inventory if not record["available"]]
    incompatible = [
        record["table"] for record in inventory if not record["schema_matches"]
    ]
    if missing:
        raise RuntimeError(
            "PostgreSQL baseline is incomplete; missing tables: " + ", ".join(missing)
        )
    if incompatible:
        raise RuntimeError(
            "PostgreSQL baseline columns do not match the reviewed schema: "
            + ", ".join(incompatible)
        )
    return inventory


def _canonical_row_bytes(payload, table):
    canonical = {
        column.name: _canonical_value(payload[column.name]) for column in table.columns
    }
    return (
        json.dumps(
            canonical,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        + b"\n"
    )


def _versioned_staged_file_evidence(path, table):
    current_digest = hashlib.sha256()
    legacy_digest = hashlib.sha256()
    rows = 0
    for payload in iter_staged_rows(path, table):
        current_digest.update(_canonical_row_bytes(payload, table))
        legacy_digest.update(_legacy_canonical_row_bytes(payload, table))
        rows += 1
    return {
        "rows": rows,
        "sha256": current_digest.hexdigest(),
        "legacy_sha256": legacy_digest.hexdigest(),
        "bytes": Path(path).stat().st_size,
    }


def _legacy_canonical_row_bytes(payload, table):
    canonical = {
        column.name: _legacy_canonical_value(payload[column.name])
        for column in table.columns
    }
    return (
        json.dumps(
            canonical,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        + b"\n"
    )


def _legacy_canonical_value(value):
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return format(value, ".17g")
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    return str(value)


def _coerce_value(value, column_type):
    if value is None:
        return None
    if isinstance(column_type, DateTime):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    if isinstance(column_type, Date) and not isinstance(column_type, DateTime):
        return date.fromisoformat(value)
    if isinstance(column_type, Time):
        return time.fromisoformat(value)
    if isinstance(column_type, Boolean):
        return bool(value)
    if isinstance(column_type, Integer):
        return int(value)
    if isinstance(column_type, Numeric):
        return Decimal(str(value))
    if isinstance(column_type, Float):
        return float(value)
    return value


def _quote_identifier(value):
    return "[" + str(value).replace("]", "]]") + "]"
