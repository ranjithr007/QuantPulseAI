"""Archive oldest decision snapshots locally before deleting them from Railway.

Railway is the source of truth.  A batch is committed to the local PostgreSQL
mirror and verified before the matching Railway rows are deleted.  The script
plans a finite number of rows from the measured database/table sizes; it does
not loop on ``pg_database_size`` because PostgreSQL keeps deleted pages until a
rewrite or partition drop.

The deletion target is intentionally limited to ``decision_snapshots``.  It is
the largest retention-managed evidence table and its rows are immutable after
creation.  Rows are taken in ascending primary-key order, which is the indexed
insertion order for this table and avoids a multi-million-row sort on Railway.
Use ``--dry-run`` first.  After trimming, a separate maintenance
window is required for ``VACUUM FULL`` (or a partition migration) to reduce
the physical volume usage shown by Railway.
"""

from __future__ import annotations

import argparse
import math
import time

import psycopg
from psycopg import sql

from setup_local_logical_mirror import local_config, railway_config


TABLE = "decision_snapshots"
SCHEMA = "legacy_local"
PROGRESS_TABLE = "_railway_trim_progress"
COLUMNS = (
    "id",
    "symbol",
    "timeframe",
    "source_timestamp",
    "effective_timestamp",
    "feature_version",
    "decision_version",
    "quality_state",
    "decision",
    "confidence",
    "regime",
    "thesis_id",
    "data_generation_id",
    "snapshot_json",
    "created_at",
    "strategy_id",
    "strategy_version",
)


def ident(*parts: str) -> sql.Identifier:
    return sql.Identifier(*parts)


def ensure_progress(local: dict) -> None:
    with psycopg.connect(**local, autocommit=True) as conn:
        conn.execute(
            sql.SQL(
                "CREATE SCHEMA IF NOT EXISTS {}"
            ).format(ident(SCHEMA))
        )
        conn.execute(
            sql.SQL(
                "CREATE TABLE IF NOT EXISTS {}.{} ("
                "singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton), "
                "source_table text NOT NULL, max_bytes bigint NOT NULL, "
                "target_bytes bigint NOT NULL, planned_rows bigint NOT NULL, "
                "processed_rows bigint NOT NULL DEFAULT 0, last_id integer NOT NULL DEFAULT 0, "
                "started_size_bytes bigint NOT NULL, phase text NOT NULL, "
                "updated_at timestamptz NOT NULL DEFAULT now())"
            ).format(ident(SCHEMA), ident(PROGRESS_TABLE))
        )
        conn.execute(
            sql.SQL("ALTER TABLE {}.{} ADD COLUMN IF NOT EXISTS last_id integer NOT NULL DEFAULT 0")
            .format(ident(SCHEMA), ident(PROGRESS_TABLE))
        )


def db_stats(conn) -> dict:
    row = conn.execute(
        """
        SELECT
            pg_database_size(current_database())::bigint AS database_bytes,
            pg_total_relation_size('public.decision_snapshots'::regclass)::bigint AS table_bytes,
            coalesce(n_live_tup, 0)::bigint AS live_rows
        FROM pg_stat_user_tables
        WHERE schemaname = 'public' AND relname = 'decision_snapshots'
        """
    ).fetchone()
    if not row:
        raise RuntimeError("public.decision_snapshots is missing on Railway")
    return {
        "database_bytes": int(row[0]),
        "table_bytes": int(row[1]),
        "live_rows": int(row[2]),
    }


def gib(value: int) -> float:
    return value / (1024**3)


def format_progress(processed: int, planned: int, stats: dict) -> str:
    remaining = max(0, planned - processed)
    completion = (processed / planned * 100.0) if planned else 100.0
    return (
        f"Processed: {processed:,} | Remaining: {remaining:,} | "
        f"Completion: {completion:.1f}% | Railway DB: {gib(stats['database_bytes']):.2f} GB"
    )


def create_plan(railway: dict, local: dict, max_gb: float, target_gb: float, safety: float) -> tuple[int, int, int]:
    max_bytes = int(max_gb * 1024**3)
    target_bytes = int(target_gb * 1024**3)
    if target_bytes >= max_bytes:
        raise ValueError("target-gb must be lower than max-gb")
    with psycopg.connect(**railway) as conn:
        stats = db_stats(conn)
    print(
        f"Railway size: {gib(stats['database_bytes']):.2f} GB | "
        f"limit: {max_gb:.2f} GB | target: {target_gb:.2f} GB | "
        f"decision_snapshots: {gib(stats['table_bytes']):.2f} GB / {stats['live_rows']:,} rows"
    )
    if stats["database_bytes"] <= max_bytes:
        return max_bytes, target_bytes, 0
    required = stats["database_bytes"] - target_bytes
    if stats["live_rows"] <= 0 or stats["table_bytes"] <= 0:
        raise RuntimeError("Cannot estimate reclaimable rows from an empty decision_snapshots table")
    estimated_bytes_per_row = stats["table_bytes"] / stats["live_rows"]
    planned = math.ceil(required / estimated_bytes_per_row * max(1.0, safety))
    planned = min(max(1, planned), stats["live_rows"])
    print(
        f"Planned oldest rows: {planned:,} | estimated reclaim after rewrite: "
        f"{gib(planned * estimated_bytes_per_row):.2f} GB"
    )
    return max_bytes, target_bytes, planned


def save_plan(local: dict, max_bytes: int, target_bytes: int, planned: int, started_size: int) -> None:
    with psycopg.connect(**local, autocommit=True) as conn:
        conn.execute(
            sql.SQL(
                "INSERT INTO {}.{} (singleton, source_table, max_bytes, target_bytes, "
                "planned_rows, processed_rows, last_id, started_size_bytes, phase) "
                "VALUES (true, %s, %s, %s, %s, 0, 0, %s, %s) "
                "ON CONFLICT (singleton) DO UPDATE SET source_table=excluded.source_table, "
                "max_bytes=excluded.max_bytes, target_bytes=excluded.target_bytes, "
                "planned_rows=excluded.planned_rows, processed_rows=0, "
                "started_size_bytes=excluded.started_size_bytes, phase=excluded.phase, updated_at=now()"
            ).format(ident(SCHEMA), ident(PROGRESS_TABLE)),
            (TABLE, max_bytes, target_bytes, planned, started_size, "planned"),
        )


def load_plan(local: dict) -> tuple[int, int, int, int, int, str]:
    with psycopg.connect(**local) as conn:
        row = conn.execute(
            sql.SQL(
                "SELECT max_bytes, target_bytes, planned_rows, processed_rows, last_id, phase "
                "FROM {}.{} WHERE singleton"
            ).format(ident(SCHEMA), ident(PROGRESS_TABLE))
        ).fetchone()
    if not row:
        raise RuntimeError("No trim plan exists; run plan first")
    return tuple(row)


def archive_batch(railway: dict, local: dict, ids: list[int]) -> None:
    columns = sql.SQL(", ").join(ident(c) for c in COLUMNS)
    source_query = sql.SQL(
        "COPY (SELECT {} FROM public.{} WHERE id = ANY(%s) ORDER BY id) "
        "TO STDOUT WITH (FORMAT binary)"
    ).format(columns, ident(TABLE))
    stage = ident("_railway_trim_stage")
    target_copy = sql.SQL("COPY {} ({}) FROM STDIN WITH (FORMAT binary)").format(stage, columns)
    upsert = sql.SQL(
        "INSERT INTO public.{} ({}) SELECT {} FROM {} "
        "ON CONFLICT (id) DO UPDATE SET {}"
    ).format(
        ident(TABLE),
        columns,
        columns,
        stage,
        sql.SQL(", ").join(
            sql.SQL("{} = EXCLUDED.{}").format(ident(c), ident(c))
            for c in COLUMNS
            if c != "id"
        ),
    )
    with psycopg.connect(**railway) as source, psycopg.connect(**local) as target:
        target.execute(
            sql.SQL("CREATE TEMP TABLE {} (LIKE public.{} INCLUDING DEFAULTS) ON COMMIT DROP")
            .format(stage, ident(TABLE))
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
            "SELECT count(*) FROM public.decision_snapshots WHERE id = ANY(%s)",
            (ids,),
        ).fetchone()[0]
        if verified < len(ids):
            raise RuntimeError(f"Local verification failed: expected {len(ids):,}, found {verified:,}")
        target.commit()


def delete_source_batch(railway: dict, ids: list[int]) -> int:
    for attempt in range(1, 6):
        try:
            with psycopg.connect(**railway) as conn:
                deleted = conn.execute(
                    "DELETE FROM public.decision_snapshots WHERE id = ANY(%s) RETURNING id",
                    (ids,),
                ).fetchall()
                conn.commit()
                return len(deleted)
        except (psycopg.OperationalError, psycopg.errors.AdminShutdown) as exc:
            if attempt == 5:
                raise
            print(f"Railway connection reset during delete (attempt {attempt}/5): {exc}")
            time.sleep(min(30, 3 * attempt))
    return 0


def trim(railway: dict, local: dict, batch_size: int) -> None:
    max_bytes, target_bytes, planned, processed, last_id, phase = load_plan(local)
    if phase == "complete" or planned == 0:
        print("No trim is required; the existing plan is complete or below the limit.")
        return
    while processed < planned:
        with psycopg.connect(**railway) as conn:
            ids = conn.execute(
                sql.SQL(
                    "SELECT {} FROM public.{} WHERE id > %s ORDER BY id ASC LIMIT %s"
                ).format(ident("id"), ident(TABLE)),
                (last_id, min(batch_size, planned - processed)),
            ).fetchall()
        if not ids:
            print("Railway has no more decision_snapshots rows to archive.")
            break
        batch_ids = [int(row[0]) for row in ids]
        upper_id = batch_ids[-1]
        with psycopg.connect(**local) as conn:
            local_ids = {
                int(row[0])
                for row in conn.execute(
                    "SELECT id FROM public.decision_snapshots WHERE id = ANY(%s)",
                    (batch_ids,),
                ).fetchall()
            }
        missing_ids = [row_id for row_id in batch_ids if row_id not in local_ids]
        if missing_ids:
            for attempt in range(1, 6):
                try:
                    archive_batch(railway, local, missing_ids)
                    break
                except (psycopg.OperationalError, psycopg.errors.AdminShutdown) as exc:
                    if attempt == 5:
                        raise
                    print(f"Railway connection reset during archive (attempt {attempt}/5): {exc}")
                    time.sleep(min(30, 3 * attempt))
        with psycopg.connect(**local) as conn:
            verified = conn.execute(
                "SELECT count(*) FROM public.decision_snapshots WHERE id = ANY(%s)",
                (batch_ids,),
            ).fetchone()[0]
        if verified != len(batch_ids):
            raise RuntimeError(
                f"Local verification failed: expected {len(batch_ids):,}, found {verified:,}"
            )
        deleted = delete_source_batch(railway, batch_ids)
        if deleted == 0:
            raise RuntimeError("No Railway rows were deleted after local verification; stopping for review")
        processed += deleted
        last_id = upper_id
        with psycopg.connect(**local, autocommit=True) as conn:
            conn.execute(
                sql.SQL(
                    "UPDATE {}.{} SET processed_rows=%s, last_id=%s, phase=%s, updated_at=now() WHERE singleton"
                ).format(ident(SCHEMA), ident(PROGRESS_TABLE)),
                (processed, last_id, "complete" if processed >= planned else "trimming"),
            )
        with psycopg.connect(**railway) as conn:
            stats = db_stats(conn)
        print(format_progress(processed, planned, stats))
    print(
        "Logical trim complete. PostgreSQL will reuse the freed pages, but the Railway "
        "volume will not shrink until a table rewrite or partition drop is performed."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["plan", "trim"])
    parser.add_argument("--max-gb", type=float, default=25.0)
    parser.add_argument("--target-gb", type=float, default=24.0)
    parser.add_argument("--safety-factor", type=float, default=1.20)
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.max_gb <= 0 or args.target_gb <= 0 or args.target_gb >= args.max_gb:
        parser.error("target-gb must be positive and lower than max-gb")
    if not 100 <= args.batch_size <= 50000:
        parser.error("batch-size must be between 100 and 50000")
    railway, local = railway_config(), local_config()
    ensure_progress(local)
    max_bytes, target_bytes, planned = create_plan(
        railway, local, args.max_gb, args.target_gb, args.safety_factor
    )
    with psycopg.connect(**railway) as conn:
        started_size = db_stats(conn)["database_bytes"]
    if args.action == "plan" or args.dry_run:
        print(f"Dry run: would archive and delete {planned:,} oldest rows.")
        return
    with psycopg.connect(**local) as conn:
        existing = conn.execute(
            sql.SQL("SELECT phase, planned_rows FROM {}.{} WHERE singleton")
            .format(ident(SCHEMA), ident(PROGRESS_TABLE))
        ).fetchone()
    if existing and existing[0] == "trimming":
        print(f"Resuming existing trim plan at phase={existing[0]}.")
    else:
        save_plan(local, max_bytes, target_bytes, planned, started_size)
    trim(railway, local, args.batch_size)


if __name__ == "__main__":
    main()
