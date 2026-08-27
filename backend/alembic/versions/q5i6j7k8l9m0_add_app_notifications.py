"""add persistent in-app notifications

Revision ID: q5i6j7k8l9m0
Revises: p4h5i6j7k8l9
"""

from alembic import op
import sqlalchemy as sa


revision = "q5i6j7k8l9m0"
down_revision = "p4h5i6j7k8l9"
branch_labels = None
depends_on = None


TABLE = "app_notifications"


def upgrade():
    bind = op.get_bind()
    if TABLE in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_key", sa.String(180), nullable=False, unique=True),
        sa.Column("category", sa.String(30), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False, server_default="INFO"),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("symbol", sa.String(30)),
        sa.Column("paper_trade_id", sa.Integer()),
        sa.Column("metadata_json", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("read_at", sa.DateTime()),
    )
    for column in (
        "event_key",
        "category",
        "event_type",
        "severity",
        "symbol",
        "paper_trade_id",
        "created_at",
        "read_at",
    ):
        op.create_index(f"ix_{TABLE}_{column}", TABLE, [column])


def downgrade():
    if TABLE in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table(TABLE)
