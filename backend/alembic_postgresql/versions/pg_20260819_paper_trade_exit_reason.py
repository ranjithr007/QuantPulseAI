"""add paper trade exit reason

Revision ID: pg_20260819_stop_reason
Revises: pg_20260815_wallet_ledger
"""

from pathlib import Path
import importlib.util


revision = "pg_20260819_stop_reason"
down_revision = "pg_20260815_wallet_ledger"
branch_labels = None
depends_on = None


_shared_path = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "l0d1e2f3a4b5_add_paper_trade_exit_reason.py"
)
_spec = importlib.util.spec_from_file_location(
    "quantpulse_paper_trade_exit_reason_migration",
    _shared_path,
)
_shared = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_shared)


def upgrade():
    _shared.upgrade()


def downgrade():
    _shared.downgrade()
