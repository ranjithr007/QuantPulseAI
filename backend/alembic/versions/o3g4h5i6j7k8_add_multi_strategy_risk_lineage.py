"""add multi-strategy risk-to-plan lineage

Revision ID: o3g4h5i6j7k8
Revises: n2f3a4b5c6d7
"""

from alembic import op
import sqlalchemy as sa


revision = "o3g4h5i6j7k8"
down_revision = "n2f3a4b5c6d7"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "risk_decisions" not in inspector.get_table_names():
        return
    columns = {
        item["name"] for item in inspector.get_columns("risk_decisions")
    }
    if "trade_plan_id" not in columns:
        op.add_column(
            "risk_decisions",
            sa.Column("trade_plan_id", sa.Integer(), nullable=True),
        )
    indexes = {
        item["name"] for item in sa.inspect(bind).get_indexes("risk_decisions")
    }
    if "ix_risk_decisions_trade_plan_id" not in indexes:
        op.create_index(
            "ix_risk_decisions_trade_plan_id",
            "risk_decisions",
            ["trade_plan_id"],
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "risk_decisions" not in inspector.get_table_names():
        return
    indexes = {
        item["name"] for item in inspector.get_indexes("risk_decisions")
    }
    if "ix_risk_decisions_trade_plan_id" in indexes:
        op.drop_index(
            "ix_risk_decisions_trade_plan_id",
            table_name="risk_decisions",
        )
    columns = {
        item["name"] for item in sa.inspect(bind).get_columns("risk_decisions")
    }
    if "trade_plan_id" in columns:
        op.drop_column("risk_decisions", "trade_plan_id")
