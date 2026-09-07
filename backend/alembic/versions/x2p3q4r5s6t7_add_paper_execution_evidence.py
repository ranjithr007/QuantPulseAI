"""Add nullable bounded execution audit fields; preserve historical paper policies.

Revision ID: x2p3q4r5s6t7
Revises: w1o2p3q4r5s6
"""
from alembic import op
import sqlalchemy as sa

revision = "x2p3q4r5s6t7"
down_revision = "w1o2p3q4r5s6"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    for table in ("paper_trades", "strategy_shadow_trades"):
        if not sa.inspect(bind).has_table(table):
            continue
        columns = {item["name"] for item in sa.inspect(bind).get_columns(table)}
        for name, kind in (("trailing_activation_r", sa.Float()), ("execution_evidence_json", sa.Text()), ("exit_evidence_json", sa.Text())):
            if name not in columns:
                op.add_column(table, sa.Column(name, kind, nullable=True))
    if sa.inspect(bind).has_table("paper_trades"):
        indexes = {item["name"] for item in sa.inspect(bind).get_indexes("paper_trades")}
        if "ix_paper_trades_closed_history" not in indexes:
            op.create_index("ix_paper_trades_closed_history", "paper_trades", ["status", "closed_at", "id"])


def downgrade():
    # Keep audit data and new-position settings when rolling back application
    # code; dropping them could silently change active challenger management.
    pass
