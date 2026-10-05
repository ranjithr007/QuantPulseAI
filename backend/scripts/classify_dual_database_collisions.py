"""Read-only check of whether colliding IDs identify the same logical record."""

from sqlalchemy import MetaData, Table, create_engine, select

from audit_dual_database_sync import _database_url


IDENTITIES = {
    "paper_trades": ("created_at", "symbol", "side"),
    "paper_wallet_ledger": ("event_key",),
    "strategy_learning_evaluations": ("strategy_id", "strategy_version", "milestone"),
    "strategy_version_configs": ("strategy_id", "version"),
}


def main():
    local = create_engine(_database_url("QUANTPULSE_SOURCE_DATABASE_URL", "mssql"), pool_pre_ping=True)
    railway = create_engine(_database_url("QUANTPULSE_TARGET_DATABASE_URL", "postgresql"), pool_pre_ping=True)
    try:
        with local.connect() as source, railway.connect() as target:
            for name, identity_columns in IDENTITIES.items():
                left = Table(name, MetaData(), autoload_with=source)
                right = Table(name, MetaData(), autoload_with=target)
                primary_key = next(iter(left.primary_key.columns)).name
                source_rows = {
                    row[primary_key]: tuple(row[column] for column in identity_columns)
                    for row in source.execute(select(left.c[primary_key], *(left.c[column] for column in identity_columns))).mappings()
                }
                target_rows = {
                    row[primary_key]: tuple(row[column] for column in identity_columns)
                    for row in target.execute(select(right.c[primary_key], *(right.c[column] for column in identity_columns))).mappings()
                }
                collisions = source_rows.keys() & target_rows.keys()
                same_identity = sum(source_rows[key] == target_rows[key] for key in collisions)
                local_only_ids = source_rows.keys() - target_rows.keys()
                target_identities = set(target_rows.values())
                local_only_already_present = sum(source_rows[key] in target_identities for key in local_only_ids)
                print(f"{name}: id_collisions={len(collisions)} same_identity={same_identity} unrelated_identity={len(collisions)-same_identity} local_only_ids={len(local_only_ids)} local_only_id_with_existing_identity={local_only_already_present}")
    finally:
        local.dispose()
        railway.dispose()


if __name__ == "__main__":
    main()
