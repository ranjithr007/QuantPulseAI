"""Add durable trade thesis lineage.

Revision ID: 5e7a9d1c8f12
Revises: 4d3e7f2b8c61, f2b6e7c1a9d4
Create Date: 2026-06-24 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "5e7a9d1c8f12"

down_revision: Union[str, Sequence[str], None] = (
    "4d3e7f2b8c61",
    "f2b6e7c1a9d4",
)

branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def table_exists(table_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return inspector.has_table(table_name)


def column_exists(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())

    return any(
        column["name"].lower() == column_name.lower()
        for column in inspector.get_columns(table_name)
    )


def index_exists(table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())

    return any(
        index.get("name") and index["name"].lower() == index_name.lower()
        for index in inspector.get_indexes(table_name)
    )


def create_index_if_missing(
    table_name: str,
    index_name: str,
    columns: list[str],
    *,
    unique: bool = False,
) -> None:
    if not index_exists(table_name, index_name):
        op.create_index(
            index_name,
            table_name,
            columns,
            unique=unique,
        )


def add_thesis_lineage_if_missing(
    table_name: str,
    index_name: str,
) -> None:
    if not column_exists(table_name, "thesis_id"):
        op.add_column(
            table_name,
            sa.Column("thesis_id", sa.Integer(), nullable=True),
        )

    create_index_if_missing(
        table_name,
        index_name,
        ["thesis_id"],
    )


def upgrade() -> None:
    if not table_exists("trade_theses"):
        op.create_table(
            "trade_theses",
            sa.Column(
                "id",
                sa.Integer(),
                primary_key=True,
                autoincrement=True,
            ),
            sa.Column(
                "thesis_key",
                sa.String(length=100),
                nullable=False,
            ),
            sa.Column(
                "symbol",
                sa.String(length=30),
                nullable=False,
            ),
            sa.Column(
                "side",
                sa.String(length=20),
                nullable=False,
            ),
            sa.Column(
                "title",
                sa.String(length=200),
                nullable=False,
            ),
            sa.Column(
                "lifecycle_state",
                sa.String(length=20),
                nullable=False,
            ),
            sa.Column(
                "lifecycle_reason",
                sa.String(length=1000),
                nullable=True,
            ),
            sa.Column(
                "source_signal",
                sa.String(length=20),
                nullable=True,
            ),
            sa.Column(
                "confidence",
                sa.Float(),
                nullable=True,
            ),
            sa.Column(
                "mode",
                sa.String(length=20),
                nullable=True,
            ),
            sa.Column(
                "entry_timeframe",
                sa.String(length=10),
                nullable=True,
            ),
            sa.Column(
                "timeframe_stack",
                sa.String(length=40),
                nullable=True,
            ),
            sa.Column(
                "regime",
                sa.String(length=50),
                nullable=True,
            ),
            sa.Column(
                "trade_plan_id",
                sa.Integer(),
                nullable=True,
            ),
            sa.Column(
                "risk_decision_id",
                sa.Integer(),
                nullable=True,
            ),
            sa.Column(
                "paper_trade_id",
                sa.Integer(),
                nullable=True,
            ),
            sa.Column(
                "assumptions_json",
                sa.Text(),
                nullable=False,
            ),
            sa.Column(
                "invalidation_json",
                sa.Text(),
                nullable=False,
            ),
            sa.Column(
                "targets_json",
                sa.Text(),
                nullable=False,
            ),
            sa.Column(
                "scenario_json",
                sa.Text(),
                nullable=True,
            ),
            sa.Column(
                "contradiction_json",
                sa.Text(),
                nullable=True,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "invalidated_at",
                sa.DateTime(),
                nullable=True,
            ),
            sa.Column(
                "resolved_at",
                sa.DateTime(),
                nullable=True,
            ),
        )

    create_index_if_missing(
        "trade_theses",
        "ix_trade_theses_thesis_key",
        ["thesis_key"],
        unique=True,
    )
    create_index_if_missing(
        "trade_theses",
        "ix_trade_theses_symbol",
        ["symbol"],
    )
    create_index_if_missing(
        "trade_theses",
        "ix_trade_theses_side",
        ["side"],
    )
    create_index_if_missing(
        "trade_theses",
        "ix_trade_theses_lifecycle_state",
        ["lifecycle_state"],
    )
    create_index_if_missing(
        "trade_theses",
        "ix_trade_theses_created_at",
        ["created_at"],
    )
    create_index_if_missing(
        "trade_theses",
        "ix_trade_theses_updated_at",
        ["updated_at"],
    )
    create_index_if_missing(
        "trade_theses",
        "ix_trade_theses_trade_plan_id",
        ["trade_plan_id"],
    )
    create_index_if_missing(
        "trade_theses",
        "ix_trade_theses_risk_decision_id",
        ["risk_decision_id"],
    )
    create_index_if_missing(
        "trade_theses",
        "ix_trade_theses_paper_trade_id",
        ["paper_trade_id"],
    )

    add_thesis_lineage_if_missing(
        "trade_plans",
        "ix_trade_plans_thesis_id",
    )
    add_thesis_lineage_if_missing(
        "risk_decisions",
        "ix_risk_decisions_thesis_id",
    )
    add_thesis_lineage_if_missing(
        "paper_trades",
        "ix_paper_trades_thesis_id",
    )


def downgrade() -> None:
    # This migration repairs databases where some objects may already
    # have existed outside Alembic history. Avoid automatically deleting
    # potentially pre-existing production schema objects.
    pass