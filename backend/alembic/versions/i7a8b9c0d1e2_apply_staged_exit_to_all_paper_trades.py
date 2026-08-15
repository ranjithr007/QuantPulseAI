"""apply staged exits to all official paper trades

Revision ID: i7a8b9c0d1e2
Revises: h6f7a8b9c0d1
"""

from datetime import datetime

from alembic import op
import sqlalchemy as sa


revision = "i7a8b9c0d1e2"
down_revision = "h6f7a8b9c0d1"
branch_labels = None
depends_on = None

POLICY = "PAPER_STAGED_EXIT_V1"
TIMEFRAMES = ("1h", "2h", "4h", "1d")


def upgrade():
    _backfill_open_paper_trades(op.get_bind())


def downgrade():
    # Existing positions may already have partially exited under this policy;
    # their prior targets cannot be reconstructed safely.
    pass


def _backfill_open_paper_trades(connection):
    paper_trades = sa.table(
        "paper_trades",
        sa.column("id", sa.Integer()),
        sa.column("trade_plan_id", sa.Integer()),
        sa.column("symbol", sa.String()),
        sa.column("side", sa.String()),
        sa.column("entry_price", sa.Float()),
        sa.column("entry_timeframe", sa.String()),
        sa.column("status", sa.String()),
        sa.column("exit_policy", sa.String()),
        sa.column("initial_stop_loss", sa.Float()),
        sa.column("stop_loss", sa.Float()),
        sa.column("target1", sa.Float()),
        sa.column("target2", sa.Float()),
        sa.column("target1_fraction", sa.Float()),
        sa.column("remaining_position_fraction", sa.Float()),
        sa.column("max_hold_hours", sa.Integer()),
        sa.column("target1_hit_at", sa.DateTime()),
    )
    trade_plans = sa.table(
        "trade_plans",
        sa.column("id", sa.Integer()),
        sa.column("side", sa.String()),
        sa.column("entry_price", sa.Float()),
        sa.column("entry_timeframe", sa.String()),
        sa.column("status", sa.String()),
        sa.column("exit_policy", sa.String()),
        sa.column("stop_loss", sa.Float()),
        sa.column("target1", sa.Float()),
        sa.column("target2", sa.Float()),
        sa.column("target1_fraction", sa.Float()),
        sa.column("max_hold_hours", sa.Integer()),
        sa.column("exit_price", sa.Float()),
        sa.column("result", sa.String()),
        sa.column("closed_at", sa.DateTime()),
    )

    active_plan_values = {}
    rows = connection.execute(
        sa.select(paper_trades).where(paper_trades.c.status == "OPEN")
    ).mappings()
    for row in rows:
        if str(row["entry_timeframe"] or "").lower() not in TIMEFRAMES:
            continue
        levels = _levels(row["side"], row["entry_price"])
        if levels is None:
            continue
        target1_complete = row["target1_hit_at"] is not None
        values = {
            "exit_policy": POLICY,
            "initial_stop_loss": levels["stop_loss"],
            "stop_loss": row["entry_price"] if target1_complete else levels["stop_loss"],
            "target1": levels["target1"],
            "target2": levels["target2"],
            "target1_fraction": 0.5,
            "remaining_position_fraction": 0.5 if target1_complete else 1.0,
            "max_hold_hours": 48,
        }
        connection.execute(
            paper_trades.update()
            .where(paper_trades.c.id == row["id"])
            .values(**values)
        )
        if row["trade_plan_id"] is not None:
            active_plan_values[row["trade_plan_id"]] = values

    plan_rows = connection.execute(
        sa.select(trade_plans).where(trade_plans.c.status == "OPEN")
    ).mappings()
    for row in plan_rows:
        active_values = active_plan_values.get(row["id"])
        if active_values is not None:
            connection.execute(
                trade_plans.update()
                .where(trade_plans.c.id == row["id"])
                .values(
                    exit_policy=POLICY,
                    stop_loss=active_values["initial_stop_loss"],
                    target1=active_values["target1"],
                    target2=active_values["target2"],
                    target1_fraction=0.5,
                    max_hold_hours=48,
                )
            )
            continue

        if str(row["entry_timeframe"] or "").lower() in TIMEFRAMES:
            connection.execute(
                trade_plans.update()
                .where(trade_plans.c.id == row["id"])
                .values(
                    status="CLOSED",
                    result="STALE_EXIT_POLICY",
                    exit_price=row["entry_price"],
                    closed_at=datetime.utcnow(),
                )
            )


def _levels(side, entry_price):
    if entry_price is None:
        return None
    entry = float(entry_price)
    direction = 1 if str(side or "").upper() in {"BUY", "LONG"} else -1
    precision = _price_precision(entry)
    return {
        "stop_loss": round(entry * (1 - direction * 0.0075), precision),
        "target1": round(entry * (1 + direction * 0.015), precision),
        "target2": round(entry * (1 + direction * 0.023), precision),
    }


def _price_precision(price):
    if price < 1:
        return 6
    if price < 10:
        return 5
    if price < 100:
        return 4
    return 2
