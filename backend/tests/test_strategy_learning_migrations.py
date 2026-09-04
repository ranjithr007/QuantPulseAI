import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"


def _module(filename, name):
    spec = importlib.util.spec_from_file_location(name, VERSIONS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_learning_migrations_correct_results_and_create_ledgers(monkeypatch):
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    def trade_table(name):
        return sa.Table(
            name,
            metadata,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("status", sa.String(20)),
            sa.Column("result", sa.String(20)),
            sa.Column("pnl_percent", sa.Float()),
        )

    shadow_trades = trade_table("strategy_shadow_trades")
    paper_trades = trade_table("paper_trades")
    metadata.create_all(engine)
    with engine.begin() as connection:
        records = [
            {"id": 1, "status": "CLOSED", "result": "LOSS", "pnl_percent": 0.4},
            {"id": 2, "status": "CLOSED", "result": "WIN", "pnl_percent": -0.8},
        ]
        connection.execute(shadow_trades.insert(), records)
        connection.execute(paper_trades.insert(), records)
        operations = Operations(MigrationContext.configure(connection))
        result_fix = _module(
            "v0n1o2p3q4r5_fix_strategy_trade_result_labels.py",
            "strategy_result_fix",
        )
        learning = _module(
            "w1o2p3q4r5s6_add_strategy_learning.py",
            "strategy_learning_schema",
        )
        monkeypatch.setattr(result_fix, "op", operations)
        monkeypatch.setattr(learning, "op", operations)

        result_fix.upgrade()
        learning.upgrade()

        for table_name in ("strategy_shadow_trades", "paper_trades"):
            rows = connection.execute(
                sa.text(f"SELECT id, result FROM {table_name} ORDER BY id")
            ).mappings().all()
            assert [row["result"] for row in rows] == ["WIN", "LOSS"]
        tables = set(sa.inspect(connection).get_table_names())
        assert "strategy_learning_evaluations" in tables
        assert "strategy_version_configs" in tables
