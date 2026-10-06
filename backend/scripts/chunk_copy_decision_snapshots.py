"""Copy decision_snapshots in committed, resumable batches.

The Railway public proxy has reset the single logical-replication table-sync
transaction several times.  This script temporarily removes only that table
from the publication, lets the other tables continue replicating, and copies
the table in small committed batches.  The final step briefly makes the
Railway database read-only, copies the rows added since the initial high-water
mark, restores the publication, and resumes the subscription.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import psycopg
from psycopg import sql

from setup_local_logical_mirror import (
    PUBLICATION,
    SUBSCRIPTION,
    local_config,
    railway_config,
)


TABLE = "decision_snapshots"
PROGRESS_SCHEMA = "legacy_local"
PROGRESS_TABLE = f"{PROGRESS_SCHEMA}._decision_snapshot_chunk_progress"
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


def qident(name: str) -> sql.Identifier:
    return sql.Identifier(name)


def progress_ident() -> sql.Identifier:
    return sql.Identifier(PROGRESS_SCHEMA, "_decision_snapshot_chunk_progress")


def ensure_progress(local: dict) -> None:
    with psycopg.connect(**local, autocommit=True) as conn:
        conn.execute(
            sql.SQL(
                "CREATE TABLE IF NOT EXISTS {}.{} ("
                "singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton), "
                "source_max_id integer, last_id integer NOT NULL DEFAULT 0, "
                "copied_rows bigint NOT NULL DEFAULT 0, phase text NOT NULL, "
                "updated_at timestamptz NOT NULL DEFAULT now())"
            ).format(qident(PROGRESS_SCHEMA), qident("_decision_snapshot_chunk_progress"))
        )


def source_table_names(railway: dict) -> list[str]:
    with psycopg.connect(**railway) as conn:
        return [r[0] for r in conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
        ).fetchall()]


def publication_without_decision(railway: dict) -> None:
    names = [n for n in source_table_names(railway) if n != TABLE]
    if not names:
        raise RuntimeError("No Railway public tables found")
    with psycopg.connect(**railway, autocommit=True) as conn:
        # PostgreSQL does not allow SET TABLE on a FOR ALL TABLES
        # publication. Recreate only the publication metadata; the logical
        # replication slot remains intact while the subscriber refreshes.
        all_tables = conn.execute(
            "SELECT puballtables FROM pg_publication WHERE pubname=%s", (PUBLICATION,)
        ).fetchone()
        if all_tables and all_tables[0]:
            conn.execute(sql.SQL("DROP PUBLICATION {} ").format(qident(PUBLICATION)))
            conn.execute(
                sql.SQL("CREATE PUBLICATION {} FOR TABLE {}")
                .format(qident(PUBLICATION), sql.SQL(", ").join(
                    sql.SQL("public.{}" ).format(qident(n)) for n in names
                ))
            )
            print("Recreated the FOR ALL publication as an explicit table list.")
            return
        conn.execute(
            sql.SQL("ALTER PUBLICATION {} SET TABLE {}")
            .format(qident(PUBLICATION), sql.SQL(", ").join(
                sql.SQL("public.{}" ).format(qident(n)) for n in names
            ))
        )
    print(f"Publication now carries {len(names)} tables; {TABLE} is copied manually.")


def refresh_subscription(local: dict, enabled: bool) -> None:
    with psycopg.connect(**local, autocommit=True) as conn:
        # PostgreSQL requires REFRESH PUBLICATION to run while the
        # subscription is enabled. Enabling first also lets the apply worker
        # settle the 48 retained tables while the decision table is absent.
        conn.execute(sql.SQL("ALTER SUBSCRIPTION {} ENABLE").format(qident(SUBSCRIPTION)))
        conn.execute(
            sql.SQL("ALTER SUBSCRIPTION {} REFRESH PUBLICATION WITH (copy_data = false)")
            .format(qident(SUBSCRIPTION))
        )
        if not enabled:
            conn.execute(sql.SQL("ALTER SUBSCRIPTION {} DISABLE").format(qident(SUBSCRIPTION)))


def prepare(railway: dict, local: dict) -> None:
    ensure_progress(local)
    with psycopg.connect(**local) as conn:
        existing = conn.execute(f"SELECT source_max_id, last_id, copied_rows, phase FROM {PROGRESS_TABLE} WHERE singleton").fetchone()
        local_rows = conn.execute("SELECT count(*) FROM public.decision_snapshots").fetchone()[0]
    if local_rows:
        raise RuntimeError(f"public.decision_snapshots is not empty ({local_rows:,} rows); refusing to reseed")
    with psycopg.connect(**railway) as conn:
        source_max = conn.execute("SELECT coalesce(max(id), 0) FROM public.decision_snapshots").fetchone()[0]
    if existing and existing[3] in {"copying", "ready_to_finalize", "finalized"}:
        print(f"Existing checkpoint retained: source_max_id={existing[0]} last_id={existing[1]} copied_rows={existing[2]} phase={existing[3]}")
        return
    publication_without_decision(railway)
    refresh_subscription(local, enabled=True)
    with psycopg.connect(**local, autocommit=True) as conn:
        conn.execute(
            sql.SQL("INSERT INTO {} (singleton, source_max_id, last_id, copied_rows, phase) "
                    "VALUES (true, %s, 0, 0, 'copying') "
                    "ON CONFLICT (singleton) DO UPDATE SET source_max_id=excluded.source_max_id, "
                    "last_id=0, copied_rows=0, phase='copying', updated_at=now()")
            .format(progress_ident()),
            (source_max,),
        )
    print(f"Prepared resumable copy through source id {source_max:,}.")


def checkpoint(local: dict) -> tuple[int, int, int, str]:
    with psycopg.connect(**local) as conn:
        row = conn.execute(f"SELECT source_max_id, last_id, copied_rows, phase FROM {PROGRESS_TABLE} WHERE singleton").fetchone()
    if not row:
        raise RuntimeError("No checkpoint found; run prepare first")
    return row


def copy_batch(railway: dict, local: dict, last_id: int, upper_id: int) -> int:
    columns = sql.SQL(", ").join(qident(c) for c in COLUMNS)
    source_query = sql.SQL(
        "COPY (SELECT {} FROM public.{} WHERE id > %s AND id <= %s ORDER BY id) "
        "TO STDOUT WITH (FORMAT binary)"
    ).format(columns, qident(TABLE))
    target_query = sql.SQL(
        "COPY public.{} ({}) FROM STDIN WITH (FORMAT binary)"
    ).format(qident(TABLE), columns)
    for attempt in range(1, 6):
        try:
            with psycopg.connect(**railway) as source, psycopg.connect(**local) as target:
                with source.cursor().copy(source_query, (last_id, upper_id)) as out_copy:
                    with target.cursor().copy(target_query) as in_copy:
                        while True:
                            block = out_copy.read()
                            if not block:
                                break
                            in_copy.write(block)
                target.commit()
                return target.execute("SELECT count(*) FROM public.decision_snapshots WHERE id > %s AND id <= %s", (last_id, upper_id)).fetchone()[0]
        except (psycopg.OperationalError, psycopg.errors.AdminShutdown) as exc:
            if attempt == 5:
                raise
            print(f"Batch connection reset (attempt {attempt}/5): {exc}")
            time.sleep(min(30, 3 * attempt))
    return 0


def copy_until(railway: dict, local: dict, batch_size: int) -> None:
    source_max, last_id, copied_rows, phase = checkpoint(local)
    if phase == "finalized":
        print("Checkpoint is already finalized.")
        return
    while last_id < source_max:
        with psycopg.connect(**railway) as conn:
            ids = conn.execute(
                "SELECT id FROM public.decision_snapshots WHERE id > %s AND id <= %s ORDER BY id LIMIT %s",
                (last_id, source_max, batch_size),
            ).fetchall()
        if not ids:
            break
        upper_id = ids[-1][0]
        count = copy_batch(railway, local, last_id, upper_id)
        copied_rows += count
        last_id = upper_id
        with psycopg.connect(**local, autocommit=True) as conn:
            conn.execute(
                f"UPDATE {PROGRESS_TABLE} SET last_id=%s, copied_rows=%s, phase='copying', updated_at=now() WHERE singleton",
                (last_id, copied_rows),
            )
        print(f"Processed: {copied_rows:,} rows | through id {last_id:,} | target {source_max:,}")
    with psycopg.connect(**local, autocommit=True) as conn:
        conn.execute(f"UPDATE {PROGRESS_TABLE} SET phase='ready_to_finalize', updated_at=now() WHERE singleton")
    print(f"Initial high-water copy complete: {copied_rows:,} rows.")


def pause_railway(railway: dict) -> None:
    with psycopg.connect(**railway, autocommit=True) as conn:
        conn.execute(sql.SQL("ALTER DATABASE {} SET default_transaction_read_only = on").format(qident(railway["dbname"])))
        conn.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE pid <> pg_backend_pid()")
    print("Railway writers paused briefly for final catch-up.")


def finalize(railway: dict, local: dict, batch_size: int) -> None:
    source_max, last_id, copied_rows, phase = checkpoint(local)
    if phase == "finalized":
        print("Already finalized.")
        return
    pause_railway(railway)
    try:
        # The database setting affects new sessions. This maintenance session is
        # explicitly writable so it can restore the publication and setting.
        with psycopg.connect(**railway) as conn:
            conn.execute("SET default_transaction_read_only = off")
            final_max = conn.execute("SELECT coalesce(max(id), 0) FROM public.decision_snapshots").fetchone()[0]
        # Reuse the same committed copier for the short delta. It is safe while
        # writers are paused, and the original high-water mark remains in the
        # checkpoint for auditability.
        with psycopg.connect(**local, autocommit=True) as conn:
            conn.execute(f"UPDATE {PROGRESS_TABLE} SET source_max_id=%s, phase='copying', updated_at=now() WHERE singleton", (final_max,))
        copy_until(railway, local, batch_size)
        with psycopg.connect(**railway, autocommit=True) as conn:
            conn.execute("SET default_transaction_read_only = off")
            conn.execute(sql.SQL("ALTER PUBLICATION {} ADD TABLE public.{} ").format(qident(PUBLICATION), qident(TABLE)))
        refresh_subscription(local, enabled=True)
        with psycopg.connect(**local, autocommit=True) as conn:
            conn.execute(f"UPDATE {PROGRESS_TABLE} SET phase='finalized', updated_at=now() WHERE singleton")
        print("decision_snapshots restored to the publication and subscription resumed.")
    finally:
        with psycopg.connect(**railway, autocommit=True) as conn:
            conn.execute("SET default_transaction_read_only = off")
            conn.execute(sql.SQL("ALTER DATABASE {} SET default_transaction_read_only = off").format(qident(railway["dbname"])))
            conn.execute("SELECT pg_reload_conf()")
        print("Railway writers resumed.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "copy", "finalize"])
    parser.add_argument("--batch-size", type=int, default=5000)
    args = parser.parse_args()
    if args.batch_size < 100 or args.batch_size > 50000:
        parser.error("batch-size must be between 100 and 50000")
    railway, local = railway_config(), local_config()
    if args.action == "prepare":
        prepare(railway, local)
    elif args.action == "copy":
        copy_until(railway, local, args.batch_size)
    else:
        finalize(railway, local, args.batch_size)


if __name__ == "__main__":
    main()
