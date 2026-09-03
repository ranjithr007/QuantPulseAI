"""add concurrent index for latest market-participation snapshots

Revision ID: pg_20260903_participation_idx
Revises: pg_20260902_pnl_indexes
"""

from alembic import op
import sqlalchemy as sa


revision = "pg_20260903_participation_idx"
down_revision = "pg_20260902_pnl_indexes"
branch_labels = None
depends_on = None


TABLE_NAME = "decision_snapshots"
INDEX_NAME = "ix_decision_snapshots_participation_latest"
COLUMNS = [
    "decision_version",
    "timeframe",
    "symbol",
    "effective_timestamp",
    "id",
]


def _index_names(bind):
    return {
        item["name"]
        for item in sa.inspect(bind).get_indexes(TABLE_NAME)
    }


def upgrade():
    bind = op.get_bind()
    if TABLE_NAME not in set(sa.inspect(bind).get_table_names()):
        return
    if INDEX_NAME in _index_names(bind):
        return
    with op.get_context().autocommit_block():
        op.create_index(
            INDEX_NAME,
            TABLE_NAME,
            COLUMNS,
            unique=False,
            postgresql_concurrently=True,
        )


def downgrade():
    bind = op.get_bind()
    if TABLE_NAME not in set(sa.inspect(bind).get_table_names()):
        return
    if INDEX_NAME not in _index_names(bind):
        return
    with op.get_context().autocommit_block():
        op.drop_index(
            INDEX_NAME,
            table_name=TABLE_NAME,
            postgresql_concurrently=True,
        )
