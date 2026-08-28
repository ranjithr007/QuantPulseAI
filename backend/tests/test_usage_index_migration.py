import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "r6j7k8l9m0n1_add_latest_evidence_indexes.py"
)


def _migration_module():
    spec = importlib.util.spec_from_file_location("usage_index_migration", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _evidence_table(metadata, table_name, columns):
    return sa.Table(
        table_name,
        metadata,
        *(sa.Column(column, sa.DateTime() if "At" in column or column == "created_at" else sa.Integer() if column.lower() == "id" else sa.String(20)) for column in columns),
    )


def test_usage_index_migration_adds_idempotent_latest_lookup_indexes(monkeypatch):
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    _evidence_table(metadata, "MarketFeatures", ["Id", "Symbol", "Timeframe", "CreatedAt"])
    _evidence_table(metadata, "MarketRegimes", ["Id", "Symbol", "Timeframe", "CreatedAt"])
    _evidence_table(metadata, "MarketOrderFlow", ["Id", "Symbol", "Timeframe", "CreatedAt"])
    _evidence_table(metadata, "market_smc_signals", ["id", "symbol", "timeframe", "created_at"])
    metadata.create_all(engine)

    expected = {name for name, _table, _columns in _migration_module().INDEXES}
    with engine.begin() as connection:
        operations = Operations(MigrationContext.configure(connection))
        module = _migration_module()
        monkeypatch.setattr(module, "op", operations)

        module.upgrade()
        module.upgrade()

        actual = {
            index["name"]
            for _name, table, _columns in module.INDEXES
            for index in sa.inspect(connection).get_indexes(table)
        }
        assert actual == expected

        module.downgrade()
        remaining = {
            index["name"]
            for _name, table, _columns in module.INDEXES
            for index in sa.inspect(connection).get_indexes(table)
        }
        assert remaining.isdisjoint(expected)
