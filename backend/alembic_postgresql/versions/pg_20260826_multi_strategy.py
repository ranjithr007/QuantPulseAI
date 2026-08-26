"""add multi-strategy risk-to-plan lineage

Revision ID: pg_20260826_multi
Revises: pg_20260826_strategy
"""

from pathlib import Path
import importlib.util


revision = "pg_20260826_multi"
down_revision = "pg_20260826_strategy"
branch_labels = None
depends_on = None


_shared_path = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "o3g4h5i6j7k8_add_multi_strategy_risk_lineage.py"
)
_spec = importlib.util.spec_from_file_location(
    "quantpulse_multi_strategy_migration",
    _shared_path,
)
_shared = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_shared)


def upgrade():
    _shared.upgrade()


def downgrade():
    _shared.downgrade()
