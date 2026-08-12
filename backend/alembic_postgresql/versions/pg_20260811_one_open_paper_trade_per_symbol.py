"""enforce one open paper trade per symbol

Revision ID: pg_20260811_one_open_symbol
Revises: pg_20260809_baseline
"""

from alembic import op
import sqlalchemy as sa


revision = "pg_20260811_one_open_symbol"
down_revision = "pg_20260809_baseline"
branch_labels = None
depends_on = None


INDEX_NAME = "uq_paper_trades_one_open_symbol"


def upgrade():
    bind = op.get_bind()
    duplicates = bind.execute(
        sa.text(
            "SELECT symbol, COUNT(*) AS open_count FROM paper_trades "
            "WHERE status = 'OPEN' GROUP BY symbol HAVING COUNT(*) > 1"
        )
    ).fetchall()
    if duplicates:
        symbols = ", ".join(str(row[0]) for row in duplicates)
        raise RuntimeError(
            "Cannot enforce QP-TI-001 while duplicate open paper trades exist: "
            + symbols
        )

    op.create_index(
        INDEX_NAME,
        "paper_trades",
        ["symbol"],
        unique=True,
        postgresql_where=sa.text("status = 'OPEN'"),
    )


def downgrade():
    op.drop_index(INDEX_NAME, table_name="paper_trades")
