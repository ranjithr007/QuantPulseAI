"""Add server-owned automation settings and audit log.

Revision ID: c41b87d2e9f0
Revises: b7c9d4f2a6e1
Create Date: 2026-06-20 09:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c41b87d2e9f0"
down_revision: Union[str, Sequence[str], None] = "b7c9d4f2a6e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "automation_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("locked", sa.Boolean(), nullable=False),
        sa.Column("emergency_stop", sa.Boolean(), nullable=False),
        sa.Column("allowed_symbols", sa.Text(), nullable=False),
        sa.Column("max_risk_per_trade", sa.Float(), nullable=False),
        sa.Column("daily_loss_limit", sa.Float(), nullable=False),
        sa.Column("max_open_trades", sa.Integer(), nullable=False),
        sa.Column("max_leverage", sa.Integer(), nullable=False),
        sa.Column("max_position_size", sa.Float(), nullable=False),
        sa.Column("min_confidence", sa.Float(), nullable=False),
        sa.Column("direction", sa.String(length=10), nullable=False),
        sa.Column("execution_mode", sa.String(length=20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "automation_settings_audit",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("setting_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("actor", sa.String(length=80), nullable=False),
        sa.Column("changed_fields", sa.Text(), nullable=False),
        sa.Column("previous_values", sa.Text(), nullable=False),
        sa.Column("new_values", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_automation_settings_audit_setting_id"), "automation_settings_audit", ["setting_id"])
    op.create_index(op.f("ix_automation_settings_audit_created_at"), "automation_settings_audit", ["created_at"])


def downgrade() -> None:
    op.drop_index(op.f("ix_automation_settings_audit_created_at"), table_name="automation_settings_audit")
    op.drop_index(op.f("ix_automation_settings_audit_setting_id"), table_name="automation_settings_audit")
    op.drop_table("automation_settings_audit")
    op.drop_table("automation_settings")
