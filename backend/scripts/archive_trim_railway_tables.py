"""Archive historical Railway tables when the database exceeds a global cap.

This job is deliberately separate from the decision snapshot copier.  Railway
deletes on published tables replicate to the local public mirror, so archived
rows are written to ``legacy_local.archive_<table>`` before the source delete.
Core configuration, paper ledgers, and trade history are not candidates here.
"""

from __future__ import annotations

import argparse
import time

import psycopg
from psycopg import sql

from setup_local_logical_mirror import local_config, railway_config


ARCHIVE_SCHEMA = "legacy_local"
PROGRESS_TABLE = "_railway_table_trim_progress"

# Largest historical/evidence tables.  Tables containing account state,
# configuration, or paper-trade history are intentionally protected.
CANDIDATES = (
    ("whale_trades", "id"),
    ("thesis_snapshots", "id"),
    ("liquidations", "id"),
    ("risk_decisions", "id"),
    ("MarketOrderFlow", "Id"),
    ("fusion_signals", "id"),
    ("market_smc_signals", "id"),
    ("orderbook_snapshots", "id"),
    ("market_candles", "id"),
    ("pipeline_job_runs", "id"),
    ("trade_theses", "id"),
    ("liquidation_heatmaps", "id"),
    ("futures_mark_prices", "id"),
    ("spot_market_candles", "id"),
    ("open_interest", "id"),
    ("order_flow_signals", "id"),
    ("whale_signals", "id"),
)


def ident(*parts: str) -> sql.Identifier:
    return sql.Identifier(*parts)


def archive_table(table: str) -> str:
    return f"archive_{table}"


def ensure_local(local: dict) -> None:
    with psycopg.connect(**local, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(ident(ARCHIVE_SCHEMA)))
        conn.execute(
            sql.SQL(
                "CREATE TABLE IF NOT EXISTS {}.{} ("
                "table_name text PRIMARY KEY, processed_rows bigint NOT NULL DEFAULT 0, "
                "last_id text, estimated_reclaimed_bytes double precision NOT NULL DEFAULT 0, "
                "phase text NOT NULL DEFAULT 'ready', updated_at timestamptz NOT NULL DEFAULT now())"
            ).format(ident(ARCHIVE_SCHEMA), ident(PROGRESS_TABLE))
        )
        for table, _ in CANDIDATES:
            conn.execute(
                sql.SQL(
                    "INSERT INTO {}.{} (table_name) VALUES (%s) ON CONFLICT (table_name) DO NOTHING"
                ).format(ident(ARCHIVE_SCHEMA), ident(PROGRESS_TABLE)),
                (table,),
            )


def ensure_archive_table(local: dict, table: str, pk: str) -> str:
    archive = archive_table(table)
    with psycopg.connect(**local, autocommit=True) as conn:
        conn.execute(
            sql.SQL("CREATE TABLE IF NOT EXISTS {}.{} (LIKE public.{} INCLUDING DEFAULTS)")
            .format(ident(ARCHIVE_SCHEMA), ident(archive), ident(table))
        )
        index_name = f"uq_{archive}_{pk}"[:60]
        conn.execute(
            sql.SQL("CREATE UNIQUE INDEX IF NOT EXISTS {} ON {}.{} ({})")
            .format(ident(index_name), ident(ARCHIVE_SCHEMA), ident(archive), ident(pk))
        )
    return archive


def table_stats(conn, table: str) -> tuple[int, int]:
    row = conn.execute(
        """
        SELECT pg_total_relation_size(c.oid)::bigint,
               coalesce(s.n_live_tup, 0)::bigint
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid
        WHERE n.nspname = 'public' AND c.relname = %s AND c.relkind = 'r'
        """,
        (table,),
    ).fetchone()
    if not row:
        return 0, 0
    return int(row[0]), int(row[1])


def db_size(conn) -> int:
    return int(conn.execute("SELECT pg_database_size(current_database())").fetchone()[0])


def archive_missing(
    railway: dict, local: dict, table: str, pk: str, columns: list[str], ids: list[object]
) -> None:
    if not ids:
        return
    archive = archive_table(table)
    column_sql = sql.SQL(", ").join(ident(c) for c in columns)
    source_query = sql.SQL(
        "COPY (SELECT {} FROM public.{} WHERE {} = ANY(%s) ORDER BY {}) "
        "TO STDOUT WITH (FORMAT binary)"
    ).format(column_sql, ident(table), ident(pk), ident(pk))
    stage = ident("_railway_table_trim_stage")
    target_copy = sql.SQL("COPY {} ({}) FROM STDIN WITH (FORMAT binary)").format(stage, column_sql)
    upsert = sql.SQL(
        "INSERT INTO {}.{} ({}) SELECT {} FROM {} "
        "ON CONFLICT ({}) DO UPDATE SET {}"
    ).format(
        ident(ARCHIVE_SCHEMA), ident(archive), column_sql, column_sql, stage, ident(pk),
        sql.SQL(", ").join(
            sql.SQL("{} = EXCLUDED.{}").format(ident(c), ident(c)) for c in columns if c != pk
        ),
    )
    with psycopg.connect(**railway) as source, psycopg.connect(**local) as target:
        target.execute(
            sql.SQL("CREATE TEMP TABLE {} (LIKE {}.{} INCLUDING DEFAULTS) ON COMMIT DROP")
            .format(stage, ident(ARCHIVE_SCHEMA), ident(archive))
        )
        with source.cursor().copy(source_query, (ids,)) as out_copy:
            with target.cursor().copy(target_copy) as in_copy:
                while True:
                    block = out_copy.read()
                    if not block:
                        break
                    in_copy.write(block)
        target.execute(upsert)
        verified = target.execute(
            sql.SQL("SELECT count(*) FROM {}.{} WHERE {} = ANY(%s)")
            .format(ident(ARCHIVE_SCHEMA), ident(archive), ident(pk)),
            (ids,),
        ).fetchone()[0]
        if verified != len(ids):
            raise RuntimeError(f"Local archive verification failed for {table}: {verified}/{len(ids)}")
        target.commit()


def delete_source(railway: dict, table: str, pk: str, ids: list[object]) -> int:
    with psycopg.connect(**railway) as conn:
        rows = conn.execute(
            sql.SQL("DELETE FROM public.{} WHERE {} = ANY(%s) RETURNING {}")
            .format(ident(table), ident(pk), ident(pk)),
            (ids,),
        ).fetchall()
        conn.commit()
        return len(rows)


def columns_for(railway: dict, table: str) -> list[str]:
    with psycopg.connect(**railway) as conn:
        return [
            row[0]
            for row in conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",
                (table,),
            ).fetchall()
        ]


def progress(local: dict, table: str) -> tuple[int, object | None, float, str]:
    with psycopg.connect(**local) as conn:
        row = conn.execute(
            sql.SQL("SELECT processed_rows,last_id,estimated_reclaimed_bytes,phase FROM {}.{} WHERE table_name=%s")
            .format(ident(ARCHIVE_SCHEMA), ident(PROGRESS_TABLE)),
            (table,),
        ).fetchone()
    return tuple(row)


def update_progress(local: dict, table: str, processed: int, last_id: object, reclaimed: float, phase: str) -> None:
    with psycopg.connect(**local, autocommit=True) as conn:
        conn.execute(
            sql.SQL(
                "UPDATE {}.{} SET processed_rows=%s,last_id=%s,estimated_reclaimed_bytes=%s,phase=%s,updated_at=now() "
                "WHERE table_name=%s"
            ).format(ident(ARCHIVE_SCHEMA), ident(PROGRESS_TABLE)),
            (processed, str(last_id), reclaimed, phase, table),
        )


def run(railway: dict, local: dict, max_gb: float, target_gb: float, batch_size: int) -> None:
    max_bytes = int(max_gb * 1024**3)
    target_bytes = int(target_gb * 1024**3)
    with psycopg.connect(**railway) as conn:
        current = db_size(conn)
    print(f"Railway database: {current / 1024**3:.2f} GB | limit {max_gb:.2f} GB | target {target_gb:.2f} GB")
    if current <= max_bytes:
        print("No table trim required; the database is below the configured ceiling.")
        return
    required = current - target_bytes
    reclaimed = 0.0
    for table, pk in CANDIDATES:
        if reclaimed >= required:
            break
        columns = columns_for(railway, table)
        if pk not in columns:
            continue
        ensure_archive_table(local, table, pk)
        processed, last_id, table_reclaimed, phase = progress(local, table)
        reclaimed += float(table_reclaimed)
        if phase == "complete":
            continue
        with psycopg.connect(**railway) as conn:
            table_bytes, live_rows = table_stats(conn, table)
        if not live_rows or not table_bytes:
            update_progress(local, table, processed, last_id or "", table_reclaimed, "complete")
            continue
        bytes_per_row = table_bytes / live_rows
        while reclaimed < required:
            cursor = last_id
            if cursor in (None, ""):
                cursor = 0 if pk.lower() == "id" or pk == "Id" else ""
            elif pk.lower() == "id" or pk == "Id":
                cursor = int(cursor)
            with psycopg.connect(**railway) as conn:
                rows = conn.execute(
                    sql.SQL("SELECT {} FROM public.{} WHERE {} > %s ORDER BY {} LIMIT %s")
                    .format(ident(pk), ident(table), ident(pk), ident(pk)),
                    (last_id if last_id not in (None, "") else 0, batch_size),
                ).fetchall()
            if not rows:
                update_progress(local, table, processed, last_id or "", table_reclaimed, "complete")
                break
            ids = [row[0] for row in rows]
            with psycopg.connect(**local) as conn:
                existing = {
                    row[0]
                    for row in conn.execute(
                        sql.SQL("SELECT {} FROM {}.{} WHERE {} = ANY(%s)")
                        .format(ident(pk), ident(ARCHIVE_SCHEMA), ident(archive_table(table)), ident(pk)),
                        (ids,),
                    ).fetchall()
                }
            missing = [value for value in ids if value not in existing]
            for attempt in range(1, 6):
                try:
                    archive_missing(railway, local, table, pk, columns, missing)
                    break
                except (psycopg.OperationalError, psycopg.errors.AdminShutdown) as exc:
                    if attempt == 5:
                        raise
                    print(f"{table}: Railway reset during archive (attempt {attempt}/5): {exc}")
                    time.sleep(min(30, attempt * 3))
            for attempt in range(1, 6):
                try:
                    deleted = delete_source(railway, table, pk, ids)
                    break
                except (psycopg.OperationalError, psycopg.errors.AdminShutdown) as exc:
                    if attempt == 5:
                        raise
                    print(f"{table}: Railway reset during delete (attempt {attempt}/5): {exc}")
                    time.sleep(min(30, attempt * 3))
            if deleted != len(ids):
                raise RuntimeError(f"{table}: expected to delete {len(ids)}, deleted {deleted}")
            processed += deleted
            last_id = ids[-1]
            table_reclaimed += deleted * bytes_per_row
            reclaimed += deleted * bytes_per_row
            update_progress(local, table, processed, last_id, table_reclaimed, "trimming")
            completion = min(100.0, reclaimed / required * 100.0)
            remaining = max(0.0, required - reclaimed)
            with psycopg.connect(**railway) as conn:
                size = db_size(conn)
            print(
                f"Table: {table} | Processed: {processed:,} | Estimated reclaimed: {reclaimed / 1024**3:.2f} GB | "
                f"Remaining estimate: {remaining / 1024**3:.2f} GB | Completion: {completion:.1f}% | "
                f"Railway DB: {size / 1024**3:.2f} GB"
            )
        update_progress(local, table, processed, last_id or "", table_reclaimed, "complete")
    if reclaimed < required:
        print("Candidates were exhausted before the target estimate was reached.")
    print("Logical table trim complete; run VACUUM FULL or use partitions to reclaim physical volume space.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-gb", type=float, default=28.0)
    parser.add_argument("--target-gb", type=float, default=27.0)
    parser.add_argument("--batch-size", type=int, default=5000)
    args = parser.parse_args()
    if args.max_gb <= 0 or args.target_gb <= 0 or args.target_gb >= args.max_gb:
        parser.error("target-gb must be positive and lower than max-gb")
    if not 100 <= args.batch_size <= 50000:
        parser.error("batch-size must be between 100 and 50000")
    railway, local = railway_config(), local_config()
    ensure_local(local)
    run(railway, local, args.max_gb, args.target_gb, args.batch_size)


if __name__ == "__main__":
    main()
