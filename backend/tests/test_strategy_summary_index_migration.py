import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "s7k8l9m0n1o2_add_strategy_summary_indexes.py"
)


def _migration_module():
    spec = importlib.util.spec_from_file_location(
        "strategy_summary_index_migration",
        MIGRATION_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_strategy_summary_indexes_are_idempotent(monkeypatch):
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    module = _migration_module()
    tables = {}
    for _name, table_name, columns in module.INDEXES:
        table = tables.get(table_name)
        if table is None:
            table = sa.Table(table_name, metadata)
            tables[table_name] = table
        existing = {column.name for column in table.columns}
        for column in columns:
            if column not in existing:
                table.append_column(
                    sa.Column(
                        column,
                        sa.Integer()
                        if column == "id"
                        else sa.DateTime()
                        if column == "created_at"
                        else sa.String(50),
                    )
                )
                existing.add(column)
    metadata.create_all(engine)

    expected = {name for name, _table, _columns in module.INDEXES}
    with engine.begin() as connection:
        operations = Operations(MigrationContext.configure(connection))
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
