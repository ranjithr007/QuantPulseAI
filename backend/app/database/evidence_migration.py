"""Guarded SQL Server to PostgreSQL evidence copy and reconciliation."""

import hashlib
import json
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy import insert
from sqlalchemy import inspect
from sqlalchemy import select
from sqlalchemy import text

from app.database.runtime import Base
from app.database import models as _models  # noqa: F401


def validate_migration_endpoints(source_engine, target_engine):
    source_backend = source_engine.url.get_backend_name()
    target_backend = target_engine.url.get_backend_name()
    if source_backend != "mssql":
        raise RuntimeError(
            f"Evidence source must be SQL Server, not {source_backend}. "
            "SQLite fallback/demo data is not canonical evidence."
        )
    if target_backend != "postgresql":
        raise RuntimeError(
            f"Evidence target must be PostgreSQL, not {target_backend}."
        )


def schema_inventory(database_engine):
    inspector = inspect(database_engine)
    available = set(inspector.get_table_names())
    records = []
    with database_engine.connect() as connection:
        for table in Base.metadata.sorted_tables:
            if table.name not in available:
                records.append(
                    {
                        "table": table.name,
                        "available": False,
                        "rows": None,
                        "primary_key": [column.name for column in table.primary_key.columns],
                        "missing_columns": [column.name for column in table.columns],
                        "extra_columns": [],
                        "schema_matches": False,
                    }
                )
                continue
            rows = connection.execute(
                select(func.count()).select_from(table)
            ).scalar_one()
            expected_columns = {column.name for column in table.columns}
            actual_columns = {
                column["name"] for column in inspector.get_columns(table.name)
            }
            records.append(
                {
                    "table": table.name,
                    "available": True,
                    "rows": int(rows),
                    "primary_key": [column.name for column in table.primary_key.columns],
                    "missing_columns": sorted(expected_columns - actual_columns),
                    "extra_columns": sorted(actual_columns - expected_columns),
                    "schema_matches": expected_columns == actual_columns,
                }
            )
    return records


def validate_source_schema(source_engine):
    inventory = schema_inventory(source_engine)
    missing = [record["table"] for record in inventory if not record["available"]]
    if missing:
        raise RuntimeError(
            "SQL Server source is missing baseline tables: " + ", ".join(missing)
        )
    incompatible = [
        record["table"] for record in inventory if not record["schema_matches"]
    ]
    if incompatible:
        raise RuntimeError(
            "SQL Server source columns do not match the reviewed schema: "
            + ", ".join(incompatible)
        )
    return inventory


def validate_empty_target(target_engine):
    inventory = schema_inventory(target_engine)
    missing = [record["table"] for record in inventory if not record["available"]]
    if missing:
        raise RuntimeError(
            "PostgreSQL baseline is incomplete; missing tables: " + ", ".join(missing)
        )
    incompatible = [
        record["table"] for record in inventory if not record["schema_matches"]
    ]
    if incompatible:
        raise RuntimeError(
            "PostgreSQL baseline columns do not match the reviewed schema: "
            + ", ".join(incompatible)
        )
    populated = {
        record["table"]: record["rows"]
        for record in inventory
        if record["rows"]
    }
    if populated:
        raise RuntimeError(
            "PostgreSQL migration target must be empty: "
            + json.dumps(populated, sort_keys=True)
        )
    return inventory


def table_checksum(connection, table, batch_size=1000):
    digest = hashlib.sha256()
    row_count = 0
    statement = select(table)
    primary_key = list(table.primary_key.columns)
    if primary_key:
        statement = statement.order_by(*primary_key)
    result = connection.execution_options(stream_results=True).execute(statement)
    for partition in result.mappings().partitions(batch_size):
        for row in partition:
            payload = {
                column.name: _canonical_value(row[column.name])
                for column in table.columns
            }
            digest.update(
                json.dumps(
                    payload,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")
            )
            digest.update(b"\n")
            row_count += 1
    return {"rows": row_count, "sha256": digest.hexdigest()}


def copy_table(source_connection, target_connection, table, batch_size=1000):
    statement = select(table)
    primary_key = list(table.primary_key.columns)
    if primary_key:
        statement = statement.order_by(*primary_key)
    result = source_connection.execution_options(stream_results=True).execute(statement)
    copied = 0
    for partition in result.mappings().partitions(batch_size):
        rows = [dict(row) for row in partition]
        if rows:
            target_connection.execute(insert(table), rows)
            copied += len(rows)
    return copied


def reconcile_evidence(source_engine, target_engine, batch_size=1000):
    records = []
    with source_engine.connect() as source, target_engine.connect() as target:
        for table in Base.metadata.sorted_tables:
            source_result = table_checksum(source, table, batch_size=batch_size)
            target_result = table_checksum(target, table, batch_size=batch_size)
            records.append(
                {
                    "table": table.name,
                    "source": source_result,
                    "target": target_result,
                    "matches": source_result == target_result,
                }
            )
    return {
        "tables": records,
        "matched": all(record["matches"] for record in records),
        "source_rows": sum(record["source"]["rows"] for record in records),
        "target_rows": sum(record["target"]["rows"] for record in records),
    }


def migrate_evidence(
    source_engine,
    target_engine,
    *,
    source_writes_paused=False,
    batch_size=1000,
):
    validate_migration_endpoints(source_engine, target_engine)
    if not source_writes_paused:
        raise RuntimeError(
            "Evidence migration requires source writes to be paused explicitly."
        )
    source_inventory = validate_source_schema(source_engine)
    validate_empty_target(target_engine)

    copied = {}
    with source_engine.connect() as source:
        source = source.execution_options(isolation_level="REPEATABLE READ")
        with source.begin():
            with target_engine.begin() as target:
                for table in Base.metadata.sorted_tables:
                    copied[table.name] = copy_table(
                        source,
                        target,
                        table,
                        batch_size=batch_size,
                    )
                _reset_postgresql_sequences(target)

    reconciliation = reconcile_evidence(
        source_engine,
        target_engine,
        batch_size=batch_size,
    )
    if not reconciliation["matched"]:
        raise RuntimeError("PostgreSQL evidence reconciliation failed.")
    return {
        "source_inventory": source_inventory,
        "copied": copied,
        "reconciliation": reconciliation,
    }


def _reset_postgresql_sequences(connection):
    preparer = connection.dialect.identifier_preparer
    for table in Base.metadata.sorted_tables:
        primary_keys = list(table.primary_key.columns)
        if len(primary_keys) != 1:
            continue
        column = primary_keys[0]
        if not column.autoincrement or column.type.python_type is not int:
            continue
        relation_name = preparer.quote(table.name)
        if table.schema:
            relation_name = f"{preparer.quote_schema(table.schema)}.{relation_name}"
        sequence = connection.execute(
            text("SELECT pg_get_serial_sequence(:table_name, :column_name)"),
            {"table_name": relation_name, "column_name": column.name},
        ).scalar_one_or_none()
        if not sequence:
            continue
        maximum = connection.execute(select(func.max(column))).scalar_one_or_none()
        if maximum is None:
            connection.execute(
                text("SELECT setval(CAST(:sequence AS regclass), 1, false)"),
                {"sequence": sequence},
            )
        else:
            connection.execute(
                text("SELECT setval(CAST(:sequence AS regclass), :value, true)"),
                {"sequence": sequence, "value": int(maximum)},
            )


def _canonical_value(value):
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        # Use Python's shortest round-trippable representation. PostgreSQL
        # DOUBLE PRECISION can expose binary noise with ``.17g`` even when the
        # SQL Server JSON source and the stored IEEE-754 value are equivalent.
        # Rendering that decimal in fixed notation also keeps scientific and
        # non-scientific representations canonically equivalent.
        return format(Decimal(str(value)), "f")
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    return str(value)
