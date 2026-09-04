"""add automatic paper strategy learning ledger

Revision ID: w1o2p3q4r5s6
Revises: v0n1o2p3q4r5
"""

from alembic import op
import sqlalchemy as sa


revision = "w1o2p3q4r5s6"
down_revision = "v0n1o2p3q4r5"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "strategy_learning_evaluations" not in tables:
        op.create_table(
            "strategy_learning_evaluations",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("strategy_id", sa.String(length=50), nullable=False),
            sa.Column("strategy_version", sa.String(length=100), nullable=False),
            sa.Column("milestone", sa.Integer(), nullable=False),
            sa.Column("window_size", sa.Integer(), nullable=False),
            sa.Column("closed_trade_count", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=40), nullable=False),
            sa.Column("metrics_json", sa.Text(), nullable=False),
            sa.Column("diagnostics_json", sa.Text(), nullable=False),
            sa.Column("recommended_changes_json", sa.Text(), nullable=False),
            sa.Column("candidate_version", sa.String(length=100), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "strategy_id",
                "strategy_version",
                "milestone",
                name="uq_strategy_learning_evaluation_milestone",
            ),
        )
        op.create_index(
            "ix_strategy_learning_evaluations_strategy_id",
            "strategy_learning_evaluations",
            ["strategy_id"],
        )
        op.create_index(
            "ix_strategy_learning_evaluations_strategy_version",
            "strategy_learning_evaluations",
            ["strategy_version"],
        )
        op.create_index(
            "ix_strategy_learning_evaluations_status",
            "strategy_learning_evaluations",
            ["status"],
        )
        op.create_index(
            "ix_strategy_learning_latest",
            "strategy_learning_evaluations",
            ["strategy_id", "strategy_version", "created_at", "id"],
        )

    if "strategy_version_configs" not in tables:
        op.create_table(
            "strategy_version_configs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("strategy_id", sa.String(length=50), nullable=False),
            sa.Column("version", sa.String(length=100), nullable=False),
            sa.Column("base_version", sa.String(length=100), nullable=False),
            sa.Column("decision_version", sa.String(length=120), nullable=False),
            sa.Column("status", sa.String(length=40), nullable=False),
            sa.Column("parameters_json", sa.Text(), nullable=False),
            sa.Column("source_evaluation_id", sa.Integer(), nullable=True),
            sa.Column("paper_execution_enabled", sa.Boolean(), nullable=False),
            sa.Column("official_paper_enabled", sa.Boolean(), nullable=False),
            sa.Column("live_execution_enabled", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "strategy_id",
                "version",
                name="uq_strategy_version_config_identity",
            ),
        )
        for column in ("strategy_id", "status", "source_evaluation_id"):
            op.create_index(
                f"ix_strategy_version_configs_{column}",
                "strategy_version_configs",
                [column],
            )


def downgrade():
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "strategy_version_configs" in tables:
        op.drop_table("strategy_version_configs")
    if "strategy_learning_evaluations" in tables:
        op.drop_table("strategy_learning_evaluations")
