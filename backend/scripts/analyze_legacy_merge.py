"""Compare staged LocalDB rows with the completed local Railway mirror.

This is read-only. An equal primary key alone does not identify the same row:
the two databases have issued keys independently.
"""

import argparse

from psycopg import sql

from stage_legacy_localdb import _local_connection


IDENTITY = {
    "MarketFeatures": ("Symbol", "Timeframe", "CreatedAt"),
    "MarketOrderFlow": ("Symbol", "Timeframe", "CreatedAt"),
    "MarketRegimes": ("Symbol", "Timeframe", "CreatedAt"),
    "app_notifications": ("event_key",),
    "backtest_results": ("symbol", "signal", "created_at"),
    "data_quality_events": ("symbol", "timeframe", "source", "category", "observed_at"),
    "paper_trades": ("created_at", "symbol", "side"),
    "paper_wallet_ledger": ("event_key",),
    "strategy_learning_evaluations": ("strategy_id", "strategy_version", "milestone"),
    "strategy_version_configs": ("strategy_id", "version"),
}


def analyze(connection, name, key, cross_id=False):
    identity = IDENTITY.get(name)
    identity_sql = sql.SQL("")
    if identity:
        left = sql.SQL(", ").join(sql.SQL("l.{}" ).format(sql.Identifier(col)) for col in identity)
        right = sql.SQL(", ").join(sql.SQL("p.{}" ).format(sql.Identifier(col)) for col in identity)
        identity_sql = sql.SQL(
            ", count(*) FILTER (WHERE p.{key} IS NOT NULL AND "
            "({left}) IS NOT DISTINCT FROM ({right})) AS same_identity_by_id"
        ).format(key=sql.Identifier(key), left=left, right=right)
    statement = sql.SQL(
        "SELECT count(*) AS staged, "
        "count(*) FILTER (WHERE p.{key} IS NULL) AS free_id, "
        "count(*) FILTER (WHERE p.{key} IS NOT NULL) AS overlapping_id{identity} "
        "FROM {legacy} l LEFT JOIN {mirror} p ON p.{key} = l.{key}"
    ).format(
        key=sql.Identifier(key), identity=identity_sql,
        legacy=sql.Identifier("legacy_local", name),
        mirror=sql.Identifier("public", name),
    )
    counts = connection.execute(statement).fetchone()
    if cross_id and identity:
        predicates = sql.SQL(" AND ").join(
            sql.SQL("p.{} = l.{}").format(sql.Identifier(col), sql.Identifier(col))
            for col in identity
        )
        cross_statement = sql.SQL(
            "SELECT count(*) FROM {legacy} l WHERE EXISTS ("
            "SELECT 1 FROM {mirror} p WHERE {predicates})"
        ).format(
            legacy=sql.Identifier("legacy_local", name),
            mirror=sql.Identifier("public", name),
            predicates=predicates,
        )
        counts = (*counts, connection.execute(cross_statement).fetchone()[0])
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", action="append", dest="tables")
    parser.add_argument("--cross-id", action="store_true", help="Find identity matches under other IDs; may scan large tables")
    args = parser.parse_args()
    with _local_connection() as connection:
        connection.execute("SET statement_timeout = '120s'")
        staged = dict(connection.execute(
            "SELECT table_name, completed FROM legacy_local._copy_progress"
        ).fetchall())
        ready = {row[0] for row in connection.execute(
            "SELECT c.relname FROM pg_subscription_rel r "
            "JOIN pg_class c ON c.oid = r.srrelid "
            "WHERE r.srsubstate = 'r'"
        ).fetchall()}
        selected = args.tables or sorted(staged)
        for name in selected:
            if not staged.get(name):
                print(f"{name}: legacy staging incomplete", flush=True)
                continue
            if name not in ready:
                print(f"{name}: Railway initial copy incomplete", flush=True)
                continue
            key = connection.execute(
                "SELECT a.attname FROM pg_index i "
                "JOIN pg_class c ON c.oid = i.indrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = i.indkey[0] "
                "WHERE n.nspname = 'public' AND c.relname = %s AND i.indisprimary "
                "AND i.indnkeyatts = 1",
                (name,),
            ).fetchone()
            if not key:
                print(f"{name}: no single-column primary key", flush=True)
                continue
            try:
                counts = analyze(connection, name, key[0], cross_id=args.cross_id)
            except Exception as exc:
                connection.rollback()
                print(f"{name}: analysis failed: {exc}", flush=True)
                continue
            labels = ["staged", "free_id", "overlapping_id"]
            if name in IDENTITY:
                labels.append("same_identity_by_id")
                if args.cross_id:
                    labels.append("same_identity_any_id")
            print(name + ": " + " ".join(
                f"{label}={value}" for label, value in zip(labels, counts)
            ), flush=True)


if __name__ == "__main__":
    main()
