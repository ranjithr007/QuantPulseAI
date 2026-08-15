"""add INR paper wallet ledger

Revision ID: k9c0d1e2f3a4
Revises: j8b9c0d1e2f3
"""

from alembic import op
import sqlalchemy as sa


revision = "k9c0d1e2f3a4"
down_revision = "j8b9c0d1e2f3"
branch_labels = None
depends_on = None


def upgrade():
    _add_trade_columns()
    ledger = _create_ledger_table()
    _backfill(op.get_bind(), ledger)


def downgrade():
    op.drop_index("ix_paper_wallet_ledger_created_at", table_name="paper_wallet_ledger")
    op.drop_index("ix_paper_wallet_ledger_symbol", table_name="paper_wallet_ledger")
    op.drop_index("ix_paper_wallet_ledger_paper_trade_id", table_name="paper_wallet_ledger")
    op.drop_table("paper_wallet_ledger")
    for name in (
        "realized_pnl_inr",
        "partial_realized_pnl_inr",
        "margin_used_inr",
        "leverage",
        "position_notional_inr",
        "allocation_percent",
        "paper_capital_at_entry_inr",
    ):
        op.drop_column("paper_trades", name)


def _add_trade_columns():
    for name in (
        "paper_capital_at_entry_inr",
        "allocation_percent",
        "position_notional_inr",
        "leverage",
        "margin_used_inr",
        "partial_realized_pnl_inr",
        "realized_pnl_inr",
    ):
        op.add_column("paper_trades", sa.Column(name, sa.Float(), nullable=True))


def _create_ledger_table():
    ledger = op.create_table(
        "paper_wallet_ledger",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_key", sa.String(length=160), nullable=False, unique=True),
        sa.Column("paper_trade_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=30), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("delta_inr", sa.Float(), nullable=False),
        sa.Column("position_notional_inr", sa.Float(), nullable=True),
        sa.Column("margin_inr", sa.Float(), nullable=True),
        sa.Column("position_fraction", sa.Float(), nullable=True),
        sa.Column("pnl_percent", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_paper_wallet_ledger_paper_trade_id",
        "paper_wallet_ledger",
        ["paper_trade_id"],
    )
    op.create_index("ix_paper_wallet_ledger_symbol", "paper_wallet_ledger", ["symbol"])
    op.create_index(
        "ix_paper_wallet_ledger_created_at",
        "paper_wallet_ledger",
        ["created_at"],
    )
    return ledger


def _backfill(connection, ledger):
    trades = sa.table(
        "paper_trades",
        sa.column("id", sa.Integer()),
        sa.column("symbol", sa.String()),
        sa.column("side", sa.String()),
        sa.column("entry_price", sa.Float()),
        sa.column("confidence", sa.Float()),
        sa.column("fee_bps", sa.Float()),
        sa.column("status", sa.String()),
        sa.column("pnl_percent", sa.Float()),
        sa.column("target1_hit_at", sa.DateTime()),
        sa.column("target1_exit_price", sa.Float()),
        sa.column("target1_fraction", sa.Float()),
        sa.column("opened_at", sa.DateTime()),
        sa.column("closed_at", sa.DateTime()),
        sa.column("created_at", sa.DateTime()),
        sa.column("paper_capital_at_entry_inr", sa.Float()),
        sa.column("allocation_percent", sa.Float()),
        sa.column("position_notional_inr", sa.Float()),
        sa.column("leverage", sa.Float()),
        sa.column("margin_used_inr", sa.Float()),
        sa.column("partial_realized_pnl_inr", sa.Float()),
        sa.column("realized_pnl_inr", sa.Float()),
    )
    rows = connection.execute(sa.select(trades)).mappings().all()
    events = []
    for row in rows:
        allocation = 75.0 if float(row["confidence"] or 0) < 60 else 85.0
        notional = 100_000.0 * allocation / 100
        margin = notional / 5.0
        realized = (
            round(notional * float(row["pnl_percent"] or 0) / 100, 2)
            if str(row["status"] or "").upper() == "CLOSED"
            else None
        )
        partial = _legacy_partial_pnl(row, notional)
        connection.execute(
            trades.update()
            .where(trades.c.id == row["id"])
            .values(
                paper_capital_at_entry_inr=100_000.0,
                allocation_percent=allocation,
                position_notional_inr=notional,
                leverage=5.0,
                margin_used_inr=margin,
                partial_realized_pnl_inr=partial,
                realized_pnl_inr=realized,
            )
        )
        opened_at = row["opened_at"] or row["created_at"]
        events.append(
            {
                "event_key": f"paper_trade:{row['id']}:ENTRY",
                "paper_trade_id": row["id"],
                "symbol": row["symbol"],
                "event_type": "ENTRY",
                "delta_inr": 0.0,
                "position_notional_inr": notional,
                "margin_inr": margin,
                "position_fraction": 1.0,
                "pnl_percent": None,
                "created_at": opened_at,
            }
        )
        if realized is not None:
            events.append(
                {
                    "event_key": f"paper_trade:{row['id']}:CLOSE",
                    "paper_trade_id": row["id"],
                    "symbol": row["symbol"],
                    "event_type": "LEGACY_CLOSE_REALIZED",
                    "delta_inr": realized,
                    "position_notional_inr": notional,
                    "margin_inr": margin,
                    "position_fraction": 1.0,
                    "pnl_percent": row["pnl_percent"],
                    "created_at": row["closed_at"] or opened_at,
                }
            )
        elif partial:
            events.append(
                {
                    "event_key": f"paper_trade:{row['id']}:TARGET1",
                    "paper_trade_id": row["id"],
                    "symbol": row["symbol"],
                    "event_type": "TARGET1_REALIZED",
                    "delta_inr": partial,
                    "position_notional_inr": notional,
                    "margin_inr": margin * float(row["target1_fraction"] or 0.5),
                    "position_fraction": float(row["target1_fraction"] or 0.5),
                    "pnl_percent": partial / notional * 100,
                    "created_at": row["target1_hit_at"],
                }
            )
    if events:
        op.bulk_insert(ledger, events)


def _legacy_partial_pnl(row, notional):
    if not row["target1_hit_at"] or row["target1_exit_price"] is None:
        return 0.0
    entry = float(row["entry_price"] or 0)
    if entry <= 0:
        return 0.0
    exit_price = float(row["target1_exit_price"])
    gross = (
        (exit_price - entry) / entry * 100
        if str(row["side"] or "").upper() == "LONG"
        else (entry - exit_price) / entry * 100
    )
    fraction = float(row["target1_fraction"] or 0.5)
    fee_percent = float(row["fee_bps"] or 7.5) * 2 / 100
    return round(notional * ((gross - fee_percent) * fraction) / 100, 2)
