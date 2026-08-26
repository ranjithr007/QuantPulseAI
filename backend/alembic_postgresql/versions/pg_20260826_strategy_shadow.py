"""add isolated strategy shadow-trade ledger

Revision ID: pg_20260826_shadow
Revises: pg_20260826_multi
"""

from pathlib import Path
import importlib.util


revision = "pg_20260826_shadow"
down_revision = "pg_20260826_multi"
branch_labels = None
depends_on = None


_shared_path = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "p4h5i6j7k8l9_add_strategy_shadow_trades.py"
)
_spec = importlib.util.spec_from_file_location(
    "quantpulse_strategy_shadow_migration",
    _shared_path,
)
_shared = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_shared)


def upgrade():
    _shared.upgrade()


def downgrade():
    _shared.downgrade()
