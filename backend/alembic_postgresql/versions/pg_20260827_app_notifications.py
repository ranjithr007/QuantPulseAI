"""add persistent in-app notifications

Revision ID: pg_20260827_notifications
Revises: pg_20260826_shadow
"""

from pathlib import Path
import importlib.util


revision = "pg_20260827_notifications"
down_revision = "pg_20260826_shadow"
branch_labels = None
depends_on = None


_shared_path = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "q5i6j7k8l9m0_add_app_notifications.py"
)
_spec = importlib.util.spec_from_file_location(
    "quantpulse_app_notification_migration",
    _shared_path,
)
_shared = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_shared)


def upgrade():
    _shared.upgrade()


def downgrade():
    _shared.downgrade()
