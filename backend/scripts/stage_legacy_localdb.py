"""Resumable copy of the read-only LocalDB snapshot into a separate local PG schema.

This preserves every legacy application row without touching Railway or the
replicated public tables. It is an archive/staging step, not the final merge.
"""

import argparse
import os
from pathlib import Path

import psycopg
from psycopg import sql
from sqlalchemy import MetaData, Table, create_engine, inspect, select, text

from audit_dual_database_sync import _database_url


LOCAL_PASSWORD = Path(r"D:\PostgreSQL\quantpulse_mirror_password.txt")


def _local_connection():
    return psycopg.connect(
        host="127.0.0.1", port=5433, user="quantpulse_mirror",
        password=LOCAL_PASSWORD.read_text(encoding="ascii").strip(),
        dbname="quantpulse_mirror",
    )


def _stage_table(source, target, table, batch_size):
    name = table.name
    key = next(iter(table.primary_key.columns))
    columns = [column.name for column in table.columns]
    target.execute(
        sql.SQL("CREATE TABLE IF NOT EXISTS {} (LIKE {} INCLUDING ALL)").format(
            sql.Identifier("legacy_local", name), sql.Identifier("public", name)
        )
    )
    target.commit()
    progress = target.execute(
        "SELECT last_key, copied_rows, completed FROM legacy_local._copy_progress WHERE table_name = %s",
        (name,),
    ).fetchone()
    if progress and progress[2]:
        print(f"{name}: already complete ({progress[1]} rows)", flush=True)
        return
    last_key = progress[0] if progress else None
    if last_key is not None and key.type.python_type is int:
        last_key = int(last_key)
    copied = progress[1] if progress else 0
    statement = select(table).order_by(key).limit(batch_size)
    if last_key is not None:
        statement = statement.where(key > last_key)
    while True:
        rows = source.execute(statement).mappings().all()
        if not rows:
            source_count = source.execute(select(text("count(*)")).select_from(table)).scalar_one()
            staged_count = target.execute(
                sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier("legacy_local", name))
            ).fetchone()[0]
            if source_count != staged_count:
                raise RuntimeError(f"{name}: source has {source_count} rows, staged {staged_count}")
            target.execute(
                "INSERT INTO legacy_local._copy_progress (table_name, last_key, copied_rows, completed) "
                "VALUES (%s, %s, %s, true) ON CONFLICT (table_name) DO UPDATE "
                "SET last_key = EXCLUDED.last_key, copied_rows = EXCLUDED.copied_rows, completed = true",
                (name, str(last_key) if last_key is not None else None, copied),
            )
            target.commit()
            print(f"{name}: complete ({copied} rows)", flush=True)
            return
        copy_statement = sql.SQL("COPY {} ({}) FROM STDIN").format(
            sql.Identifier("legacy_local", name),
            sql.SQL(", ").join(map(sql.Identifier, columns)),
        )
        with target.cursor() as cursor:
            with cursor.copy(copy_statement) as copy:
                for row in rows:
                    copy.write_row(tuple(row[column] for column in columns))
        last_key = rows[-1][key.name]
        copied += len(rows)
        target.execute(
            "INSERT INTO legacy_local._copy_progress (table_name, last_key, copied_rows, completed) "
            "VALUES (%s, %s, %s, false) ON CONFLICT (table_name) DO UPDATE "
            "SET last_key = EXCLUDED.last_key, copied_rows = EXCLUDED.copied_rows, completed = false",
            (name, str(last_key), copied),
        )
        target.commit()
        if copied % 10000 < batch_size:
            print(f"{name}: {copied} rows", flush=True)
        statement = select(table).where(key > last_key).order_by(key).limit(batch_size)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", action="append", dest="tables")
    parser.add_argument("--batch-size", type=int, default=1000)
    args = parser.parse_args()
    if args.batch_size < 1:
        parser.error("--batch-size must be positive")
    source_url = _database_url("QUANTPULSE_SOURCE_DATABASE_URL", "mssql")
    if "QuantPulseAI_Migration" not in source_url:
        raise RuntimeError("Source must be the read-only QuantPulseAI_Migration snapshot")
    source_engine = create_engine(source_url, pool_pre_ping=True, connect_args={"timeout": 10})
    try:
        with source_engine.connect() as source, _local_connection() as target:
            database_name, is_read_only = source.execute(
                text("SELECT DB_NAME(), DATABASEPROPERTYEX(DB_NAME(), 'Updateability')")
            ).one()
            if database_name != "QuantPulseAI_Migration" or is_read_only != "READ_ONLY":
                raise RuntimeError("Source database must be the read-only migration snapshot")
            target.execute("CREATE SCHEMA IF NOT EXISTS legacy_local")
            target.execute(
                "CREATE TABLE IF NOT EXISTS legacy_local._copy_progress ("
                "table_name text PRIMARY KEY, last_key text, copied_rows bigint NOT NULL, "
                "completed boolean NOT NULL DEFAULT false)"
            )
            target.commit()
            available = set(inspect(source).get_table_names()) - {"alembic_version"}
            selected = set(args.tables) if args.tables else available
            if not selected <= available:
                raise RuntimeError(f"Unknown source tables: {sorted(selected - available)}")
            for name in sorted(selected):
                table = Table(name, MetaData(), autoload_with=source)
                if len(table.primary_key.columns) != 1:
                    raise RuntimeError(f"{name} needs one primary key for resumable staging")
                _stage_table(source, target, table, args.batch_size)
    finally:
        source_engine.dispose()


if __name__ == "__main__":
    main()
