from datetime import datetime

import sqlalchemy as sa

from alembic_postgresql.versions.pg_20260815_all_staged_exit import (
    _backfill_open_paper_trades,
)


def test_open_positions_are_backfilled_and_unexecuted_plans_are_invalidated():
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    trade_plans = sa.Table(
        "trade_plans",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("side", sa.String),
        sa.Column("entry_price", sa.Float),
        sa.Column("entry_timeframe", sa.String),
        sa.Column("status", sa.String),
        sa.Column("exit_policy", sa.String),
        sa.Column("stop_loss", sa.Float),
        sa.Column("target1", sa.Float),
        sa.Column("target2", sa.Float),
        sa.Column("target1_fraction", sa.Float),
        sa.Column("max_hold_hours", sa.Integer),
        sa.Column("exit_price", sa.Float),
        sa.Column("result", sa.String),
        sa.Column("closed_at", sa.DateTime),
    )
    paper_trades = sa.Table(
        "paper_trades",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("trade_plan_id", sa.Integer),
        sa.Column("symbol", sa.String),
        sa.Column("side", sa.String),
        sa.Column("entry_price", sa.Float),
        sa.Column("entry_timeframe", sa.String),
        sa.Column("status", sa.String),
        sa.Column("exit_policy", sa.String),
        sa.Column("initial_stop_loss", sa.Float),
        sa.Column("stop_loss", sa.Float),
        sa.Column("target1", sa.Float),
        sa.Column("target2", sa.Float),
        sa.Column("target1_fraction", sa.Float),
        sa.Column("remaining_position_fraction", sa.Float),
        sa.Column("max_hold_hours", sa.Integer),
        sa.Column("target1_hit_at", sa.DateTime),
    )
    metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(
            trade_plans.insert(),
            [
                {"id": 1, "side": "LONG", "entry_price": 76.2808, "entry_timeframe": "4h", "status": "OPEN", "stop_loss": 72.3615, "target1": 84.7876, "target2": 88.9559},
                {"id": 2, "side": "SHORT", "entry_price": 1.0038, "entry_timeframe": "1h", "status": "OPEN", "stop_loss": 1.0555, "target1": 0.89163, "target2": 0.83665},
            ],
        )
        connection.execute(
            paper_trades.insert(),
            {
                "id": 1,
                "trade_plan_id": 1,
                "symbol": "SOLUSDT",
                "side": "LONG",
                "entry_price": 76.2808,
                "entry_timeframe": "4h",
                "status": "OPEN",
                "stop_loss": 72.3615,
                "target1": 84.7876,
                "target2": 88.9559,
            },
        )

        _backfill_open_paper_trades(connection)

        trade = connection.execute(sa.select(paper_trades)).mappings().one()
        assert trade["exit_policy"] == "PAPER_STAGED_EXIT_V1"
        assert trade["stop_loss"] == 75.7087
        assert trade["target1"] == 77.425
        assert trade["target2"] == 78.0353
        assert trade["target1_fraction"] == 0.5
        assert trade["remaining_position_fraction"] == 1.0
        assert trade["max_hold_hours"] == 48

        plans = {
            row["id"]: row
            for row in connection.execute(sa.select(trade_plans)).mappings()
        }
        assert plans[1]["exit_policy"] == "PAPER_STAGED_EXIT_V1"
        assert plans[1]["status"] == "OPEN"
        assert plans[2]["status"] == "CLOSED"
        assert plans[2]["result"] == "STALE_EXIT_POLICY"
        assert isinstance(plans[2]["closed_at"], datetime)
