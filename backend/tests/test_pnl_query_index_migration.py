import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "t8l9m0n1o2p3_add_pnl_query_indexes.py"
)


def _migration_module():
    spec = importlib.util.spec_from_file_location(
        "pnl_query_index_migration",
        MIGRATION_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_query_indexes_are_idempotent(monkeypatch):
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    sa.Table(
        "paper_trades",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("status", sa.String(20)),
        sa.Column("entry_timeframe", sa.String(10)),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("closed_at", sa.DateTime()),
    )
    metadata.create_all(engine)
    module = _migration_module()
    sa.Table(
        "strategy_shadow_trades",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("status", sa.String(20)),
        sa.Column("closed_at", sa.DateTime()),
    )
    sa.Table(
        "whale_trades",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("symbol", sa.String(20)),
        sa.Column("trade_time", sa.DateTime()),
    )
    sa.Table(
        "whale_signals",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("symbol", sa.String(20)),
        sa.Column("created_at", sa.DateTime()),
    )
    sa.Table(
        "liquidations",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("symbol", sa.String(20)),
        sa.Column("event_time", sa.DateTime()),
    )
    sa.Table(
        "liquidation_heatmaps",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("symbol", sa.String(20)),
        sa.Column("created_at", sa.DateTime()),
    )
    sa.Table(
        "open_interest",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("symbol", sa.String(20)),
        sa.Column("timestamp", sa.DateTime()),
    )
    sa.Table(
        "futures_mark_prices",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("symbol", sa.String(20)),
        sa.Column("timeframe", sa.String(10)),
        sa.Column("is_final", sa.Boolean()),
        sa.Column("close_time", sa.DateTime()),
    )
    sa.Table(
        "futures_margin_brackets",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("symbol", sa.String(20)),
        sa.Column("effective_at", sa.DateTime()),
    )
    sa.Table(
        "pipeline_runs",
        metadata,
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("status", sa.String(20)),
        sa.Column("completed_at", sa.DateTime()),
    )
    metadata.create_all(engine)
    expected = {
        table_name: {
            name
            for candidate_table, name, _columns in module.INDEXES
            if candidate_table == table_name
        }
        for table_name in (
            "paper_trades",
            "strategy_shadow_trades",
            "whale_trades",
            "whale_signals",
            "liquidations",
            "liquidation_heatmaps",
            "open_interest",
            "futures_mark_prices",
            "futures_margin_brackets",
            "pipeline_runs",
        )
    }

    with engine.begin() as connection:
        operations = Operations(MigrationContext.configure(connection))
        monkeypatch.setattr(module, "op", operations)

        module.upgrade()
        module.upgrade()

        for table_name, expected_names in expected.items():
            actual = {
                index["name"]
                for index in sa.inspect(connection).get_indexes(table_name)
            }
            assert expected_names.issubset(actual)

        module.downgrade()
        for table_name, expected_names in expected.items():
            remaining = {
                index["name"]
                for index in sa.inspect(connection).get_indexes(table_name)
            }
            assert remaining.isdisjoint(expected_names)

    engine.dispose()
