"""Print logical-copy progress without changing either database."""

import argparse
import time

import psycopg

from setup_local_logical_mirror import local_config, railway_config


def read_progress():
    with psycopg.connect(**railway_config()) as upstream:
        total_rows, total_bytes = upstream.execute(
            "SELECT count(*), pg_total_relation_size('public.decision_snapshots'::regclass) "
            "FROM public.decision_snapshots"
        ).fetchone()
        copy = upstream.execute(
            "SELECT tuples_processed, bytes_processed FROM pg_stat_progress_copy "
            "WHERE relid = 'public.decision_snapshots'::regclass"
        ).fetchone()
    with psycopg.connect(**local_config()) as downstream:
        local_rows = downstream.execute(
            "SELECT count(*) FROM public.decision_snapshots"
        ).fetchone()[0]
        state = downstream.execute(
            "SELECT srsubstate FROM pg_subscription_rel r "
            "JOIN pg_class c ON c.oid = r.srrelid "
            "WHERE c.relname = 'decision_snapshots'"
        ).fetchone()
    processed_rows = copy[0] if copy else (local_rows if state and state[0] == "r" else 0)
    processed_bytes = copy[1] if copy else total_bytes
    remaining_rows = max(total_rows - processed_rows, 0)
    remaining_bytes = max(total_bytes - processed_bytes, 0)
    completion = (processed_rows / total_rows * 100) if total_rows else 100.0
    return {
        "processed_rows": processed_rows,
        "remaining_rows": remaining_rows,
        "completion": completion,
        "remaining_gb": remaining_bytes / 1_000_000_000,
        "local_rows": local_rows,
        "state": state[0] if state else "missing",
    }


def print_progress(progress):
    print(f"Processed: {progress['processed_rows']:,} rows")
    print(f"Remaining: {progress['remaining_rows']:,} rows")
    print(f"Completion: {progress['completion']:.1f}%")
    print(f"Remaining size: approximately {progress['remaining_gb']:.1f} GB")
    print(f"Local table state: {progress['state']} (local committed rows: {progress['local_rows']:,})")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watch", action="store_true", help="poll until the target percentage is reached")
    parser.add_argument("--interval", type=int, default=60, help="seconds between checks")
    parser.add_argument("--until-percent", type=float, default=100.0)
    args = parser.parse_args()
    if args.interval < 1 or not 0 < args.until_percent <= 100:
        parser.error("interval must be positive and until-percent must be between 0 and 100")
    while True:
        progress = read_progress()
        print_progress(progress)
        if not args.watch or progress["completion"] >= args.until_percent:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
