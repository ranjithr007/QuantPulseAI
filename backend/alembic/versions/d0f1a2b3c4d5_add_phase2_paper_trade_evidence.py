"""add phase2 paper trade evidence

Revision ID: d0f1a2b3c4d5
Revises: c9e0f1a2b3d4
"""

from alembic import op
import sqlalchemy as sa


revision = "d0f1a2b3c4d5"
down_revision = "c9e0f1a2b3d4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "paper_trades",
        sa.Column("data_generation_id", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "paper_trades",
        sa.Column(
            "validation_contract_version",
            sa.String(length=100),
            nullable=True,
        ),
    )
    op.add_column(
        "paper_trades",
        sa.Column("fill_model_version", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "paper_trades",
        sa.Column("planned_entry_price", sa.Float(), nullable=True),
    )
    op.add_column(
        "paper_trades",
        sa.Column("entry_slippage_percent", sa.Float(), nullable=True),
    )
    op.add_column(
        "paper_trades",
        sa.Column("exit_slippage_percent", sa.Float(), nullable=True),
    )
    op.add_column(
        "paper_trades",
        sa.Column("funding_rate_snapshot", sa.Float(), nullable=True),
    )
    op.add_column(
        "paper_trades",
        sa.Column("open_interest_snapshot", sa.Float(), nullable=True),
    )
    op.add_column(
        "paper_trades",
        sa.Column("open_interest_change_percent", sa.Float(), nullable=True),
    )
    op.create_index(
        "ix_paper_trades_data_generation_id",
        "paper_trades",
        ["data_generation_id"],
        unique=False,
    )


def downgrade():
    op.drop_index(
        "ix_paper_trades_data_generation_id",
        table_name="paper_trades",
    )
    op.drop_column("paper_trades", "open_interest_change_percent")
    op.drop_column("paper_trades", "open_interest_snapshot")
    op.drop_column("paper_trades", "funding_rate_snapshot")
    op.drop_column("paper_trades", "exit_slippage_percent")
    op.drop_column("paper_trades", "entry_slippage_percent")
    op.drop_column("paper_trades", "planned_entry_price")
    op.drop_column("paper_trades", "fill_model_version")
    op.drop_column("paper_trades", "validation_contract_version")
    op.drop_column("paper_trades", "data_generation_id")
