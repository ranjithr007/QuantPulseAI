"""add composite index for latest market participation snapshots

Revision ID: u9m0n1o2p3q4
Revises: t8l9m0n1o2p3
"""

from alembic import op
import sqlalchemy as sa


revision = "u9m0n1o2p3q4"
down_revision = "t8l9m0n1o2p3"
branch_labels = None
depends_on = None


INDEX_NAME = "ix_decision_snapshots_participation_latest"
TABLE_NAME = "decision_snapshots"
COLUMNS = [
    "decision_version",
    "timeframe",
    "symbol",
    "effective_timestamp",
    "id",
]


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE_NAME not in set(inspector.get_table_names()):
        return
    indexes = {item["name"] for item in inspector.get_indexes(TABLE_NAME)}
    if INDEX_NAME not in indexes:
        op.create_index(INDEX_NAME, TABLE_NAME, COLUMNS, unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE_NAME not in set(inspector.get_table_names()):
        return
    indexes = {item["name"] for item in inspector.get_indexes(TABLE_NAME)}
    if INDEX_NAME in indexes:
        op.drop_index(INDEX_NAME, table_name=TABLE_NAME)
