"""derive strategy trade results from final net pnl

Revision ID: v0n1o2p3q4r5
Revises: u9m0n1o2p3q4
"""

from alembic import op
import sqlalchemy as sa


revision = "v0n1o2p3q4r5"
down_revision = "u9m0n1o2p3q4"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    for table_name in ("strategy_shadow_trades", "paper_trades"):
        if table_name not in tables:
            continue
        op.execute(
            sa.text(
                f"UPDATE {table_name} "
                "SET result = CASE WHEN pnl_percent > 0 THEN 'WIN' ELSE 'LOSS' END "
                "WHERE UPPER(status) = 'CLOSED' AND pnl_percent IS NOT NULL"
            )
        )


def downgrade():
    # Previous trigger labels cannot be reconstructed reliably.  Keeping the
    # correct cost-adjusted result is safer than reintroducing corrupted data.
    pass
