"""Index Phase 2 opportunity history by version and observation time.

Revision ID: y3q4r5s6t7u8
Revises: x2p3q4r5s6t7
"""

from alembic import op
import sqlalchemy as sa


revision = "y3q4r5s6t7u8"
down_revision = "x2p3q4r5s6t7"
branch_labels = None
depends_on = None


INDEX_NAME = "ix_decision_snapshots_opportunity_history"


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("decision_snapshots"):
        return
    indexes = {
        item["name"]
        for item in inspector.get_indexes("decision_snapshots")
    }
    if INDEX_NAME not in indexes:
        op.create_index(
            INDEX_NAME,
            "decision_snapshots",
            ["decision_version", "created_at", "id"],
        )


def downgrade():
    # Retain the non-destructive read-performance index on rollback.
    pass
