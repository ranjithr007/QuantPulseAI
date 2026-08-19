"""add paper trade exit reason

Revision ID: l0d1e2f3a4b5
Revises: k9c0d1e2f3a4
"""

from alembic import op
import sqlalchemy as sa


revision = "l0d1e2f3a4b5"
down_revision = "k9c0d1e2f3a4"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    columns = {item["name"] for item in inspector.get_columns("paper_trades")}
    if "exit_reason" not in columns:
        op.add_column(
            "paper_trades",
            sa.Column("exit_reason", sa.String(length=30), nullable=True),
        )

    inspector = sa.inspect(op.get_bind())
    indexes = {item["name"] for item in inspector.get_indexes("paper_trades")}
    if "ix_paper_trades_exit_reason" not in indexes:
        op.create_index(
            "ix_paper_trades_exit_reason",
            "paper_trades",
            ["exit_reason"],
        )


def downgrade():
    inspector = sa.inspect(op.get_bind())
    indexes = {item["name"] for item in inspector.get_indexes("paper_trades")}
    if "ix_paper_trades_exit_reason" in indexes:
        op.drop_index("ix_paper_trades_exit_reason", table_name="paper_trades")

    inspector = sa.inspect(op.get_bind())
    columns = {item["name"] for item in inspector.get_columns("paper_trades")}
    if "exit_reason" in columns:
        op.drop_column("paper_trades", "exit_reason")
