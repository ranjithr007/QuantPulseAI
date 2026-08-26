from sqlalchemy import create_engine, inspect, text

from app.database.bootstrap import ensure_sqlite_strategy_attribution_schema
from app.strategies.registry import LEGACY_UNATTRIBUTED_STRATEGY_ID
from app.strategies.registry import LEGACY_UNATTRIBUTED_STRATEGY_VERSION


def test_legacy_sqlite_strategy_tables_are_upgraded_backfilled_and_indexed():
    engine = create_engine("sqlite:///:memory:")
    legacy_tables = {
        "decision_snapshots": (
            "decision_version VARCHAR(40)",
            "decision_version",
            "phase2_opportunity_ledger_v1",
        ),
        "trade_plans": ("status VARCHAR(20)", "status", "OPEN"),
        "risk_decisions": ("decision VARCHAR(40)", "decision", "APPROVED"),
        "paper_trades": ("status VARCHAR(20)", "status", "OPEN"),
    }
    with engine.begin() as connection:
        for table_name, (definition, column_name, value) in legacy_tables.items():
            connection.execute(
                text(
                    f"CREATE TABLE {table_name} "
                    f"(id INTEGER PRIMARY KEY, {definition})"
                )
            )
            connection.execute(
                text(
                    f"INSERT INTO {table_name} (id, {column_name}) "
                    f"VALUES (1, :value)"
                ),
                {"value": value},
            )

    ensure_sqlite_strategy_attribution_schema(engine)
    ensure_sqlite_strategy_attribution_schema(engine)

    inspector = inspect(engine)
    for table_name in legacy_tables:
        columns = {column["name"] for column in inspector.get_columns(table_name)}
        assert {"strategy_id", "strategy_version"}.issubset(columns)
        indexes = {index["name"] for index in inspector.get_indexes(table_name)}
        assert f"ix_{table_name}_strategy_id" in indexes
        assert f"ix_{table_name}_strategy_version" in indexes
        if table_name != "decision_snapshots":
            assert "strategy_decision_snapshot_id" in columns
            assert f"ix_{table_name}_strategy_decision_snapshot_id" in indexes

        with engine.connect() as connection:
            row = connection.execute(
                text(
                    f"SELECT strategy_id, strategy_version FROM {table_name} "
                    "WHERE id = 1"
                )
            ).mappings().one()
        assert row["strategy_id"] == LEGACY_UNATTRIBUTED_STRATEGY_ID
        assert row["strategy_version"] == LEGACY_UNATTRIBUTED_STRATEGY_VERSION
