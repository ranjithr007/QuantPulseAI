"""Read-only inventory before reconciling LocalDB with Railway PostgreSQL.

This deliberately does not copy rows. Independent identity generators can assign
the same primary key to different records; a blind two-way copy would corrupt
references between application tables.
"""

import argparse
import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import closing
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import MetaData, Table, create_engine, func, inspect, select
from sqlalchemy.engine import make_url


INTERNAL_TABLES = {"alembic_version"}


def _database_url(name, expected_backend):
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} must be set in the environment")
    if value.startswith("postgres://"):
        value = "postgresql+psycopg://" + value.removeprefix("postgres://")
    elif value.startswith("postgresql://"):
        value = "postgresql+psycopg://" + value.removeprefix("postgresql://")
    backend = make_url(value).get_backend_name()
    if backend != expected_backend:
        raise RuntimeError(f"{name} must use {expected_backend}, got {backend}")
    return value


def _shape(inspector, name):
    return {
        "columns": sorted(column["name"] for column in inspector.get_columns(name)),
        "primary_key": inspector.get_pk_constraint(name).get("constrained_columns") or [],
    }


def _canonical(value):
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, (float, Decimal)):
        return format(Decimal(str(value)), "f")
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    return str(value)


def _rows(connection, table, batch_size):
    result = connection.execution_options(stream_results=True).execute(
        select(table)
    )
    for partition in result.mappings().partitions(batch_size):
        for row in partition:
            yield row


def compare_rows(local, railway, local_table, railway_table, batch_size=1000):
    """Count local-only, Railway-only, and divergent primary keys without writes."""

    key_name = list(local_table.primary_key.columns)[0].name
    result = {
        "local_only": 0,
        "railway_only": 0,
        "matching": 0,
        "conflicting": 0,
        "conflict_key_samples": [],
    }
    with tempfile.TemporaryDirectory(prefix="quantpulse-sync-audit-") as directory:
        with closing(sqlite3.connect(os.path.join(directory, "keys.sqlite"))) as keys:
            keys.execute("CREATE TABLE local_rows (key TEXT PRIMARY KEY, digest TEXT NOT NULL, seen INTEGER NOT NULL DEFAULT 0)")
            for row in _rows(local, local_table, batch_size):
                keys.execute(
                    "INSERT INTO local_rows (key, digest) VALUES (?, ?)",
                    (_row_key(row[key_name]), _row_digest(row, local_table)),
                )
            keys.commit()
            for row in _rows(railway, railway_table, batch_size):
                key = _row_key(row[key_name])
                match = keys.execute("SELECT digest FROM local_rows WHERE key = ?", (key,)).fetchone()
                if match is None:
                    result["railway_only"] += 1
                    continue
                if match[0] == _row_digest(row, railway_table):
                    result["matching"] += 1
                else:
                    result["conflicting"] += 1
                    if len(result["conflict_key_samples"]) < 10:
                        result["conflict_key_samples"].append(_canonical(row[key_name]))
                keys.execute("UPDATE local_rows SET seen = 1 WHERE key = ?", (key,))
            result["local_only"] = keys.execute(
                "SELECT count(*) FROM local_rows WHERE seen = 0"
            ).fetchone()[0]
    return result


def _row_key(value):
    return json.dumps(_canonical(value), ensure_ascii=False, separators=(",", ":"))


def _row_digest(row, table):
    payload = {
        column.name: _canonical(row[column.name]) for column in table.columns
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def audit(local_engine, railway_engine, *, scan_conflicts=False, batch_size=1000):
    local_inspector = inspect(local_engine)
    railway_inspector = inspect(railway_engine)
    local_names = set(local_inspector.get_table_names()) - INTERNAL_TABLES
    railway_names = set(railway_inspector.get_table_names()) - INTERNAL_TABLES
    report = {
        "read_only": True,
        "local_backend": local_engine.url.get_backend_name(),
        "railway_backend": railway_engine.url.get_backend_name(),
        "local_only_tables": sorted(local_names - railway_names),
        "railway_only_tables": sorted(railway_names - local_names),
        "tables": [],
    }
    with local_engine.connect() as local, railway_engine.connect() as railway:
        for name in sorted(local_names & railway_names):
            local_shape = _shape(local_inspector, name)
            railway_shape = _shape(railway_inspector, name)
            compatible = local_shape == railway_shape and len(local_shape["primary_key"]) == 1
            record = {
                "table": name,
                "compatible": compatible,
                "local_shape": local_shape,
                "railway_shape": railway_shape,
            }
            if compatible:
                local_table = Table(name, MetaData(), autoload_with=local_engine)
                railway_table = Table(name, MetaData(), autoload_with=railway_engine)
                record["local_rows"] = int(local.execute(select(func.count()).select_from(local_table)).scalar_one())
                record["railway_rows"] = int(railway.execute(select(func.count()).select_from(railway_table)).scalar_one())
                if scan_conflicts:
                    record["row_comparison"] = compare_rows(
                        local, railway, local_table, railway_table, batch_size=batch_size
                    )
            report["tables"].append(record)
    report["compatible_tables"] = sum(record["compatible"] for record in report["tables"])
    report["incompatible_tables"] = [
        record["table"] for record in report["tables"] if not record["compatible"]
    ]
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scan-conflicts", action="store_true", help="stream all rows to identify primary-key conflicts")
    parser.add_argument("--batch-size", type=int, default=1000)
    args = parser.parse_args()
    if args.batch_size < 1:
        parser.error("--batch-size must be positive")

    local_url = _database_url("QUANTPULSE_SOURCE_DATABASE_URL", "mssql")
    railway_url = _database_url("QUANTPULSE_TARGET_DATABASE_URL", "postgresql")
    local_engine = create_engine(local_url, pool_pre_ping=True, connect_args={"timeout": 5})
    railway_engine = create_engine(railway_url, pool_pre_ping=True, connect_args={"connect_timeout": 5})
    try:
        print(json.dumps(audit(local_engine, railway_engine, scan_conflicts=args.scan_conflicts, batch_size=args.batch_size), indent=2))
    finally:
        local_engine.dispose()
        railway_engine.dispose()


if __name__ == "__main__":
    main()
