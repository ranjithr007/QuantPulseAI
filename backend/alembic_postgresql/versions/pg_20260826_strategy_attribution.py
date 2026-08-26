"""add durable strategy attribution

Revision ID: pg_20260826_strategy
Revises: pg_20260823_evidence
"""

from pathlib import Path
import importlib.util


revision = "pg_20260826_strategy"
down_revision = "pg_20260823_evidence"
branch_labels = None
depends_on = None


_shared_path = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "n2f3a4b5c6d7_add_strategy_attribution.py"
)
_spec = importlib.util.spec_from_file_location(
    "quantpulse_strategy_attribution_migration",
    _shared_path,
)
_shared = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_shared)


def upgrade():
    _shared.upgrade()


def downgrade():
    _shared.downgrade()
