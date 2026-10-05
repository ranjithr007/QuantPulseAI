"""Reconcile the frozen cutover backup into the staged LocalDB history.

Run after stage_legacy_localdb.py completes. Each batch is atomic and
resumable. Railway/public tables are never written by this script.
"""

import argparse

from psycopg import sql
from sqlalchemy import MetaData, Table, create_engine, inspect, select, text

from audit_dual_database_sync import _database_url
from stage_legacy_localdb import _local_connection


def refresh_table(source, target, table, batch_size):
    name = table.name
    key = next(iter(table.primary_key.columns))
    columns = [column.name for column in table.columns]
    nonkey = [column for column in columns if column != key.name]
    progress = target.execute(
        "SELECT last_key, scanned_rows, completed FROM legacy_local._refresh_progress "
        "WHERE table_name = %s", (name,)
    ).fetchone()
    if progress and progress[2]:
        print(f"{name}: already refreshed ({progress[1]} rows)", flush=True)
        return
    copied = target.execute(
        "SELECT completed FROM legacy_local._copy_progress WHERE table_name = %s",
        (name,),
    ).fetchone()
    if not copied or not copied[0]:
        raise RuntimeError(f"{name}: initial staging must complete before refresh")
    last_key = progress[0] if progress else None
    if last_key is not None and key.type.python_type is int:
        last_key = int(last_key)
    scanned = progress[1] if progress else 0
    target.execute("DROP TABLE IF EXISTS pg_temp._refresh_batch")
    target.execute(
        sql.SQL("CREATE TEMP TABLE _refresh_batch (LIKE {} INCLUDING DEFAULTS)").format(
            sql.Identifier("legacy_local", name)
        )
    )
    target.commit()
    while True:
        statement = select(table).order_by(key).limit(batch_size)
        if last_key is not None:
            statement = statement.where(key > last_key)
        rows = source.execute(statement).mappings().all()
        if not rows:
            source_count = source.execute(select(text("count(*)")).select_from(table)).scalar_one()
            staged_count = target.execute(
                sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier("legacy_local", name))
            ).fetchone()[0]
            if staged_count < source_count:
                raise RuntimeError(f"{name}: cutover has {source_count} rows but staging has {staged_count}")
            target.execute(
                "INSERT INTO legacy_local._refresh_progress "
                "(table_name, last_key, scanned_rows, completed) VALUES (%s, %s, %s, true) "
                "ON CONFLICT (table_name) DO UPDATE SET last_key = EXCLUDED.last_key, "
                "scanned_rows = EXCLUDED.scanned_rows, completed = true",
                (name, str(last_key) if last_key is not None else None, scanned),
            )
            target.commit()
            print(f"{name}: refreshed ({scanned} cutover rows)", flush=True)
            return
        target.execute("TRUNCATE pg_temp._refresh_batch")
        copy_sql = sql.SQL("COPY pg_temp._refresh_batch ({}) FROM STDIN").format(
            sql.SQL(", ").join(map(sql.Identifier, columns))
        )
        with target.cursor() as cursor:
            with cursor.copy(copy_sql) as copy:
                for row in rows:
                    copy.write_row(tuple(row[column] for column in columns))
        insert_sql = sql.SQL(
            "INSERT INTO {} AS dst ({}) SELECT {} FROM pg_temp._refresh_batch WHERE true "
            "ON CONFLICT ({}) DO UPDATE SET {} WHERE ({}) IS DISTINCT FROM ({})"
        ).format(
            sql.Identifier("legacy_local", name),
            sql.SQL(", ").join(map(sql.Identifier, columns)),
            sql.SQL(", ").join(map(sql.Identifier, columns)),
            sql.Identifier(key.name),
            sql.SQL(", ").join(
                sql.SQL("{} = EXCLUDED.{}").format(sql.Identifier(column), sql.Identifier(column))
                for column in nonkey
            ),
            sql.SQL(", ").join(
                sql.SQL("dst.{}").format(sql.Identifier(column)) for column in nonkey
            ),
            sql.SQL(", ").join(
                sql.SQL("EXCLUDED.{}").format(sql.Identifier(column)) for column in nonkey
            ),
        )
        target.execute(insert_sql)
        last_key = rows[-1][key.name]
        scanned += len(rows)
        target.execute(
            "INSERT INTO legacy_local._refresh_progress "
            "(table_name, last_key, scanned_rows, completed) VALUES (%s, %s, %s, false) "
            "ON CONFLICT (table_name) DO UPDATE SET last_key = EXCLUDED.last_key, "
            "scanned_rows = EXCLUDED.scanned_rows, completed = false",
            (name, str(last_key), scanned),
        )
        target.commit()
        if scanned % 10000 < batch_size:
            print(f"{name}: scanned {scanned} cutover rows", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", action="append", dest="tables")
    parser.add_argument("--batch-size", type=int, default=5000)
    args = parser.parse_args()
    if args.batch_size < 1:
        parser.error("--batch-size must be positive")
    source_url = _database_url("QUANTPULSE_SOURCE_DATABASE_URL", "mssql")
    if "QuantPulseAI_Cutover" not in source_url:
        raise RuntimeError("Source must be the frozen QuantPulseAI_Cutover restore")
    engine = create_engine(source_url, pool_pre_ping=True, connect_args={"timeout": 10})
    try:
        with engine.connect() as source, _local_connection() as target:
            name, updateability = source.execute(
                text("SELECT DB_NAME(), DATABASEPROPERTYEX(DB_NAME(), 'Updateability')")
            ).one()
            if name != "QuantPulseAI_Cutover" or updateability != "READ_ONLY":
                raise RuntimeError("Cutover source database must be read-only")
            target.execute(
                "CREATE TABLE IF NOT EXISTS legacy_local._refresh_progress ("
                "table_name text PRIMARY KEY, last_key text, scanned_rows bigint NOT NULL, "
                "completed boolean NOT NULL DEFAULT false)"
            )
            target.commit()
            available = set(inspect(source).get_table_names()) - {"alembic_version"}
            selected = set(args.tables) if args.tables else available
            if not selected <= available:
                raise RuntimeError(f"Unknown cutover tables: {sorted(selected - available)}")
            for table_name in sorted(selected):
                table = Table(table_name, MetaData(), autoload_with=source)
                if len(table.primary_key.columns) != 1:
                    raise RuntimeError(f"{table_name}: expected one primary key")
                refresh_table(source, target, table, args.batch_size)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
