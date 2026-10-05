"""Configure a Railway publisher and a local PostgreSQL subscriber in stages.

The Railway wal_level change requires a separate Railway service restart. Run
``status`` before and after that restart. Passwords stay in ignored local files.
"""

import argparse
import os
from pathlib import Path
from urllib.parse import unquote, urlsplit

import psycopg
from psycopg.conninfo import make_conninfo
from psycopg import sql


PUBLICATION = "quantpulse_local_mirror"
SUBSCRIPTION = "quantpulse_local_mirror"
LOCAL_PASSWORD = Path(r"D:\PostgreSQL\quantpulse_mirror_password.txt")
RAILWAY_PASSFILE = Path(r"D:\PostgreSQL\quantpulse_railway_pgpass.conf")


def railway_config():
    raw = os.getenv("QUANTPULSE_TARGET_DATABASE_URL", "").strip()
    if not raw:
        repo_root = Path(__file__).resolve().parents[2]
        for line in (repo_root / ".env.pg3").read_text(encoding="utf-8").splitlines():
            if line.startswith("QUANTPULSE_TARGET_DATABASE_URL="):
                raw = line.split("=", 1)[1].strip().strip('"')
                break
    raw = raw.replace("postgresql+psycopg://", "postgresql://", 1)
    url = urlsplit(raw)
    if url.scheme not in {"postgres", "postgresql"} or not url.hostname or not url.username or not url.password:
        raise RuntimeError("A complete Railway PostgreSQL URL is required in .env.pg3")
    return {
        "host": url.hostname,
        "port": url.port or 5432,
        "user": unquote(url.username),
        "password": unquote(url.password),
        "dbname": unquote(url.path.lstrip("/")),
        "sslmode": "require",
    }


def local_config():
    return {
        "host": "127.0.0.1",
        "port": 5433,
        "user": "quantpulse_mirror",
        "password": LOCAL_PASSWORD.read_text(encoding="ascii").strip(),
        "dbname": "quantpulse_mirror",
    }


def status(railway, local):
    with psycopg.connect(**railway) as upstream:
        wal_level = upstream.execute("SHOW wal_level").fetchone()[0]
        publication = upstream.execute(
            "SELECT puballtables FROM pg_publication WHERE pubname = %s", (PUBLICATION,)
        ).fetchone()
        slot = upstream.execute(
            "SELECT active, wal_status, pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn) "
            "FROM pg_replication_slots WHERE slot_name = %s", (SUBSCRIPTION,)
        ).fetchone()
        print(f"railway_wal_level={wal_level} publication_all_tables={publication[0] if publication else None} slot={slot}")
    with psycopg.connect(**local) as downstream:
        sub = downstream.execute(
            "SELECT subenabled FROM pg_subscription WHERE subname = %s", (SUBSCRIPTION,)
        ).fetchone()
        tables = downstream.execute(
            "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'"
        ).fetchone()[0]
        if sub:
            states = downstream.execute(
                "SELECT srsubstate, count(*) FROM pg_subscription_rel "
                "WHERE srsubid = (SELECT oid FROM pg_subscription WHERE subname = %s) "
                "GROUP BY srsubstate ORDER BY srsubstate", (SUBSCRIPTION,)
            ).fetchall()
            copying = downstream.execute(
                "SELECT c.relname, r.srsubstate FROM pg_subscription_rel r "
                "JOIN pg_class c ON c.oid = r.srrelid "
                "WHERE r.srsubid = (SELECT oid FROM pg_subscription WHERE subname = %s) "
                "AND r.srsubstate <> 'r' ORDER BY r.srsubstate, c.relname LIMIT 8",
                (SUBSCRIPTION,),
            ).fetchall()
            size = downstream.execute("SELECT pg_database_size(current_database())").fetchone()[0]
            print(f"local_tables={tables} local_bytes={size} subscription_enabled={sub[0]} table_states={states} first_pending={copying}")
        else:
            print(f"local_tables={tables} subscription=None")


def configure_railway(railway):
    with psycopg.connect(**railway, autocommit=True) as upstream:
        user, is_superuser = upstream.execute(
            "SELECT current_user, (SELECT rolsuper FROM pg_roles WHERE rolname = current_user)"
        ).fetchone()
        if not is_superuser:
            raise RuntimeError(f"Railway role {user} must be superuser to change wal_level")
        wal_level = upstream.execute("SHOW wal_level").fetchone()[0]
        if wal_level != "logical":
            upstream.execute("ALTER SYSTEM SET wal_level = 'logical'")
            print("Railway wal_level=logical is pending a PostgreSQL service restart.")
        else:
            print("Railway wal_level is already logical.")
        limit = upstream.execute("SHOW max_slot_wal_keep_size").fetchone()[0]
        if limit == "-1":
            upstream.execute("ALTER SYSTEM SET max_slot_wal_keep_size = '8GB'")
            upstream.execute("SELECT pg_reload_conf()")
            print("Railway replication slot WAL retention capped at 8GB; a long offline period may require reseeding.")


def publish(railway):
    with psycopg.connect(**railway, autocommit=True) as upstream:
        if upstream.execute("SHOW wal_level").fetchone()[0] != "logical":
            raise RuntimeError("Railway must restart with wal_level=logical first")
        existing = upstream.execute(
            "SELECT puballtables FROM pg_publication WHERE pubname = %s", (PUBLICATION,)
        ).fetchone()
        if existing is None:
            upstream.execute(
                sql.SQL("CREATE PUBLICATION {} FOR ALL TABLES").format(sql.Identifier(PUBLICATION))
            )
            print("Created Railway publication for all application tables.")
        elif existing[0]:
            print("Railway publication already covers all tables.")
        else:
            raise RuntimeError("Existing publication with this name does not cover all tables")


def subscribe(railway, local):
    if not RAILWAY_PASSFILE.exists():
        raise RuntimeError(f"Create the private Railway passfile first: {RAILWAY_PASSFILE}")
    with psycopg.connect(**railway) as upstream:
        if upstream.execute("SHOW wal_level").fetchone()[0] != "logical":
            raise RuntimeError("Railway wal_level is not logical")
        if not upstream.execute(
            "SELECT puballtables FROM pg_publication WHERE pubname = %s", (PUBLICATION,)
        ).fetchone():
            raise RuntimeError("Railway publication is missing")
    with psycopg.connect(**local, autocommit=True) as downstream:
        if downstream.execute(
            "SELECT 1 FROM pg_subscription WHERE subname = %s", (SUBSCRIPTION,)
        ).fetchone():
            print("Local subscription already exists.")
            return
        table_count = downstream.execute(
            "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'"
        ).fetchone()[0]
        if table_count != 49:
            raise RuntimeError(f"Expected 49 local tables before subscribing, found {table_count}")
        nonempty = downstream.execute(
            "SELECT relname FROM pg_stat_user_tables WHERE schemaname = 'public' AND n_live_tup > 0"
        ).fetchall()
        if nonempty:
            raise RuntimeError("Local mirror tables are not empty; refusing initial copy")
        upstream_conninfo = make_conninfo(
            host=railway["host"],
            port=railway["port"],
            user=railway["user"],
            dbname=railway["dbname"],
            sslmode="require",
            passfile=str(RAILWAY_PASSFILE),
        )
        downstream.execute(
            sql.SQL("CREATE SUBSCRIPTION {} CONNECTION {} PUBLICATION {} "
                    "WITH (copy_data = true, create_slot = true, streaming = on)").format(
                sql.Identifier(SUBSCRIPTION),
                sql.Literal(upstream_conninfo),
                sql.Identifier(PUBLICATION),
            )
        )
        print("Local subscription created; initial copy has started.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["status", "configure-railway", "publish", "subscribe"])
    args = parser.parse_args()
    railway = railway_config()
    local = local_config()
    if args.action == "status":
        status(railway, local)
    elif args.action == "configure-railway":
        configure_railway(railway)
    elif args.action == "publish":
        publish(railway)
    else:
        subscribe(railway, local)


if __name__ == "__main__":
    main()
