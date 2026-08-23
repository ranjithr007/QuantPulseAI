"""add durable backtest market evidence

Revision ID: pg_20260823_evidence
Revises: pg_20260819_stop_reason
"""

from pathlib import Path
import importlib.util


revision = "pg_20260823_evidence"
down_revision = "pg_20260819_stop_reason"
branch_labels = None
depends_on = None


_shared_path = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "m1e2f3a4b5c6_add_backtest_market_evidence.py"
)
_spec = importlib.util.spec_from_file_location(
    "quantpulse_backtest_market_evidence_migration",
    _shared_path,
)
_shared = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_shared)


def upgrade():
    _shared.upgrade()


def downgrade():
    _shared.downgrade()
