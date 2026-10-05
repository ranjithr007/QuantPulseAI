"""Read-only inventory of Railway natural keys and foreign keys for LocalDB merge planning."""

from sqlalchemy import create_engine, inspect

from audit_dual_database_sync import _database_url


def main():
    engine = create_engine(_database_url("QUANTPULSE_TARGET_DATABASE_URL", "postgresql"), pool_pre_ping=True)
    try:
        inspector = inspect(engine)
        for name in sorted(inspector.get_table_names()):
            if name == "alembic_version":
                continue
            keys = [item["column_names"] for item in inspector.get_unique_constraints(name)]
            keys.extend(item["column_names"] for item in inspector.get_indexes(name) if item.get("unique"))
            foreign = [
                (item["constrained_columns"], item["referred_table"], item["referred_columns"])
                for item in inspector.get_foreign_keys(name)
            ]
            print(f"{name}: unique={keys} foreign={foreign}")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
