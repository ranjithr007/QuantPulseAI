from sqlalchemy import inspect, text


PAPER_EXECUTION_COLUMNS = {
    "trailing_activation_r": "FLOAT",
    "execution_evidence_json": "TEXT",
    "exit_evidence_json": "TEXT",
}

OPPORTUNITY_HISTORY_INDEX = "ix_decision_snapshots_opportunity_history"
STRATEGY_SUMMARY_INDEXES = {
    "decision_snapshots": (
        "ix_decision_snapshots_strategy_summary",
        ("strategy_id", "strategy_version", "decision_version", "symbol", "created_at", "id"),
    ),
    "trade_plans": (
        "ix_trade_plans_strategy_summary",
        ("strategy_id", "strategy_version", "created_at"),
    ),
    "risk_decisions": (
        "ix_risk_decisions_strategy_summary",
        ("strategy_id", "strategy_version", "created_at"),
    ),
    "paper_trades": (
        "ix_paper_trades_strategy_summary",
        ("strategy_id", "strategy_version", "created_at", "id"),
    ),
    "strategy_shadow_trades": (
        "ix_strategy_shadow_trades_strategy_summary",
        ("strategy_id", "strategy_version", "created_at", "id"),
    ),
}


def ensure_paper_execution_schema(engine):
    """Repair small additive schema used by safety-critical runtime jobs.

    LocalDB is scoped to the interactive Windows user and can be unavailable to
    a separate pre-start migration process even though the application process
    can connect. These nullable additions are safe and idempotent; Alembic's
    matching migration remains authoritative for ordinary deployments.
    """
    inspector = inspect(engine)
    dialect = str(engine.dialect.name).lower()
    changed = False

    with engine.begin() as connection:
        if not inspector.has_table("fast_exit_heartbeats"):
            from app.database.operational_tables import fast_exit_heartbeats

            fast_exit_heartbeats.create(bind=connection, checkfirst=True)
            changed = True

        for table_name in ("paper_trades", "strategy_shadow_trades"):
            if not inspector.has_table(table_name):
                continue
            existing = {
                column["name"] for column in inspector.get_columns(table_name)
            }
            for column_name, column_type in PAPER_EXECUTION_COLUMNS.items():
                if column_name in existing:
                    continue
                add_keyword = "ADD" if dialect == "mssql" else "ADD COLUMN"
                connection.execute(
                    text(
                        f"ALTER TABLE {table_name} {add_keyword} "
                        f"{column_name} {column_type} NULL"
                    )
                )
                changed = True

        if inspector.has_table("decision_snapshots"):
            indexes = {
                item["name"]
                for item in inspector.get_indexes("decision_snapshots")
            }
            if OPPORTUNITY_HISTORY_INDEX not in indexes:
                connection.execute(
                    text(
                        "CREATE INDEX "
                        f"{OPPORTUNITY_HISTORY_INDEX} "
                        "ON decision_snapshots "
                        "(decision_version, created_at, id)"
                    )
                )
                changed = True

        for table_name, (index_name, columns) in STRATEGY_SUMMARY_INDEXES.items():
            if not inspector.has_table(table_name):
                continue
            existing_columns = {
                item["name"] for item in inspector.get_columns(table_name)
            }
            if not set(columns).issubset(existing_columns):
                continue
            indexes = {
                item["name"] for item in inspector.get_indexes(table_name)
            }
            if index_name in indexes:
                continue
            quoted_columns = ", ".join(columns)
            connection.execute(
                text(
                    f"CREATE INDEX {index_name} "
                    f"ON {table_name} ({quoted_columns})"
                )
            )
            changed = True
    return changed
